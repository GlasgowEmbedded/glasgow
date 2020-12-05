import argparse
import asyncio
import logging
import re
import time
import sys
import csv
import yarl
import aiohttp


__all__ = ["DataLogger", "STDOUTDataLogger"]


class DataLogger:
    all_data_loggers = {}

    def __init_subclass__(cls, name):
        cls.all_data_loggers[name] = cls

    help = "applet help missing"
    description = "applet description missing"

    @classmethod
    def add_subparsers(cls, parser):
        p_data_logger = parser.add_subparsers(dest="data_logger", metavar="DATA-LOGGER")
        for name, subcls in cls.all_data_loggers.items():
            p_data_logger_subcls = p_data_logger.add_parser(
                name, help=subcls.help, description=subcls.description)
            subcls.add_arguments(p_data_logger_subcls)

    @classmethod
    def add_arguments(cls, parser):
        pass

    async def __new__(cls, logger, args, **init_kwargs):
        subcls = cls.all_data_loggers[args.data_logger or "stdout"]
        data_logger = object.__new__(subcls)
        data_logger.__init__(logger, **init_kwargs)
        await data_logger.setup(args)
        return data_logger

    def __init__(self, logger, *, field_names):
        assert "timestamp" not in field_names
        self.logger      = logger
        self.field_names = field_names

    async def setup(self, args):
        pass

    async def report_data(self, fields, timestamp=None):
        raise NotImplementedError

    async def report_error(self, message, *args, exception=None, **kwargs):
        self.logger.error(str(message).format(*args, **kwargs), exc_info=exception)


class STDOUTDataLogger(DataLogger, name="stdout"):
    help = "log data to standard output"
    description = """
    Log data to standard output in a human-readable format.
    """

    async def setup(self, args):
        self.format = "[{timestamp}] " + ", ".join([
            "{}={{{}}}".format(name, key) for key, name in self.field_names.items()
        ]) + "\n"
        self.stream = sys.stdout

    async def report_data(self, fields, timestamp=None):
        timestamp = time.gmtime(timestamp)
        line = self.format.format(timestamp=time.strftime("%Y%m%dT%H%M%SZ", timestamp), **fields)
        self.stream.write(line)
        self.stream.flush()


class CSVDataLogger(DataLogger, name="csv"):
    help = "log data to a CSV file"
    description = """
    Log data to a comma-separated value (CSV) file.
    """

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            "--dialect", metavar="DIALECT", choices=csv.list_dialects(), default="excel",
            help="format CSV file according to DIALECT")
        parser.add_argument(
            "csv_file", metavar="CSV-FILE", type=argparse.FileType("w"),
            help="write data to CSV-FILE")

    async def setup(self, args):
        self.file = args.csv_file
        self.csv_writer = csv.DictWriter(self.file, dialect=args.dialect,
                                         fieldnames=["timestamp", *self.field_names])
        self.csv_writer.writerow({
            "timestamp": "t(UTC)",
            **self.field_names
        })

    async def report_data(self, fields, timestamp=None):
        timestamp = time.gmtime(timestamp)
        self.csv_writer.writerow({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", timestamp),
            **fields
        })
        self.file.flush()


class InfluxDBDataLogger(DataLogger, name="influxdb"):
    help = "log data to an InfluxDB 1.x endpoint"
    description = """
    Log data to an InfluxDB 1.x endpoint over HTTP(S).
    """

    @staticmethod
    def _escape_name(charset, value):
        return re.sub(r"([{}])".format(charset), r"\\\1", value)

    @staticmethod
    def _escape_value(value):
        if isinstance(value, (float, int)):
            return str(value)
        if isinstance(value, str):
            return re.sub(r"([\"\\])", r"\\\1", value)
        if isinstance(value, bool):
            return "true" if value else "false"
        assert False

    @staticmethod
    def _timestamp(precision, value):
        if precision == "ns":
            return int(value * 1e9)
        if precision == "us":
            return int(value * 1e6)
        if precision == "ms":
            return int(value * 1e3)
        if precision == "s":
            return int(value)
        if precision == "m":
            return int(value / 60)
        if precision == "h":
            return int(value / 3600)
        assert False

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            "endpoint", metavar="ENDPOINT", type=str,
            help="write to endpoint URL //ENDPOINT/write")
        parser.add_argument(
            "database", metavar="DATABASE", type=str,
            help="write to database DATABASE")
        parser.add_argument(
            "-r", "--retention-policy", metavar="POLICY",
            help="write to retention policy POLICY")
        parser.add_argument(
            "measurement", metavar="SERIES", type=str,
            help="write to measurement SERIES")
        def tag(arg):
            if "=" not in arg:
                raise argparse.ArgumentTypeError("{} is not a valid tag".format(arg))
            key, value = arg.split("=", 1)
            return key, value
        parser.add_argument(
            "-t", "--tag", metavar="TAG=VALUE", dest="tags", type=tag,
            action="append", default=[],
            help="attach TAG=VALUE to all data points")
        parser.add_argument(
            "-p", "--precision", metavar="PRECISION",
            choices=["ns", "us", "ms", "s", "m", "h"], required=True,
            help="set timestamp precision to PRECISION")
        parser.add_argument(
            "--batch-size", metavar="BATCH-SIZE", type=int, default=1,
            help="submit data in groups of BATCH-SIZE points")

    async def setup(self, args):
        url = yarl.URL(args.endpoint)
        url = url.with_path("/write")
        url = url.with_query(db=args.database)
        if args.retention_policy:
            url = url.update_query(rp=args.retention_policy)
        if args.precision:
            url = url.update_query(precision=args.precision)
        self.url = url
        self.series = ",".join([
            self._escape_name(", ", args.measurement),
            *[self._escape_name(",= ", key) + "=" + self._escape_name(",= ", value)
              for key, value in args.tags]
        ])
        self.precision = args.precision
        self.session = aiohttp.ClientSession()
        self._queue = []
        self._batch_size = args.batch_size

    async def _report(self, fields, timestamp=None):
        data_parts = [self.series]
        data_parts.append(",".join(self._escape_name(",= ", key) + "=" +
                                   self._escape_value(fields[key])
                                   for key in fields))
        if timestamp is None:
            # If the timestamp is not specified, InfluxDB will timestamp the data point with
            # the request timestamp. This works just fine with one data point per request, but
            # if batching is enabled, then, since the series is always same, only one point per
            # batch will ever be recorded. To avoid that, batched requests must be timestamped
            # during submission. To achieve consistent behavior in case the local clock and
            # the InfluxDB server clock are different, all requests are timestamped during
            # submission regardless of whether batching is enabled.
            timestamp = time.time()
        data_parts.append(str(self._timestamp(self.precision, timestamp)))
        data = " ".join(data_parts)

        self.logger.debug("InfluxDB: queue data=<%s>", data)
        self._queue.append(data)

        if len(self._queue) >= self._batch_size:
            try:
                async with self.session.post(self.url, data="\n".join(self._queue)) as response:
                    if response.status not in range(200, 300):
                        self.logger.error("InfluxDB: write status=%d body=%s",
                                          response.status, (await response.text()).strip())
                    self._queue.clear()
            except aiohttp.ClientError as error:
                self.logger.error("InfluxDB: http error=%s", str(error), exc_info=error)
                # don't clear queue on network error

    async def report_data(self, fields, timestamp=None):
        assert set(fields) == set(self.field_names)
        await self._report({"error": False, **fields}, timestamp)

    async def report_error(self, message, *args, exception=None, **kwargs):
        await super().report_error(message, *args, **kwargs, exception=exception)
        await self._report({"error": True})


class InfluxDB2DataLogger(DataLogger, name="influxdb2"):
    help = "log data to an InfluxDB 2.x endpoint"
    description = """
    Log data to an InfluxDB 2.x endpoint over HTTP(S).
    """

    # see https://docs.influxdata.com/influxdb/v2.0/query-data/execute-queries/influx-api/
    # see https://docs.influxdata.com/influxdb/cloud/api/#tag/Write

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            "endpoint", metavar="ENDPOINT", type=str,
            help="write to endpoint URL //ENDPOINT/api/v2/write")
        parser.add_argument(
            "org", metavar="ORGANIZATION", type=str,
            help="write to Organization ORGANIZATION (can be either the name or the id)")
        parser.add_argument(
            "bucket", metavar="BUCKET", type=str,
            help="write to bucket BUCKET")
        parser.add_argument(
            "measurement", metavar="SERIES", type=str,
            help="write to measurement SERIES")
        def tag(arg):
            if "=" not in arg:
                raise argparse.ArgumentTypeError("{} is not a valid tag".format(arg))
            key, value = arg.split("=", 1)
            return key, value
        parser.add_argument(
            "-t", "--tag", metavar="TAG=VALUE", dest="tags", type=tag,
            action="append", default=[],
            help="attach TAG=VALUE to all data points")
        parser.add_argument(
            "-p", "--precision", metavar="PRECISION",
            choices=["ns", "us", "ms", "s", "m", "h"], required=True,
            help="set timestamp precision to PRECISION")
        parser.add_argument(
            "--batch-size", metavar="BATCH-SIZE", type=int, default=1,
            help="submit data in groups of BATCH-SIZE points")
        parser.add_argument(
            "--token", metavar="TOKEN", type=str, required=True,
            help="set the Token to use for Authentication")

    async def setup(self, args):
        url = yarl.URL(args.endpoint)
        url = url.with_path("/api/v2/write")
        url = url.with_query(org=args.org, bucket=args.bucket)
        if args.precision:
            url = url.update_query(precision=args.precision)
        self.url = url
        self.token = args.token
        self.series = ",".join([
            InfluxDBDataLogger._escape_name(", ", args.measurement),
            *[InfluxDBDataLogger._escape_name(",= ", key) + "=" + InfluxDBDataLogger._escape_name(",= ", value)
              for key, value in args.tags]
        ])
        self.precision = args.precision
        self.session = aiohttp.ClientSession()
        self._queue = []
        self._batch_size = args.batch_size

    async def _report(self, fields, timestamp=None):
        data_parts = [self.series]
        data_parts.append(",".join(InfluxDBDataLogger._escape_name(",= ", key) + "=" +
                                   InfluxDBDataLogger._escape_value(fields[key])
                                   for key in fields))
        if timestamp is None:
            # If the timestamp is not specified, InfluxDB will timestamp the data point with
            # the request timestamp. This works just fine with one data point per request, but
            # if batching is enabled, then, since the series is always same, only one point per
            # batch will ever be recorded. To avoid that, batched requests must be timestamped
            # during submission. To achieve consistent behavior in case the local clock and
            # the InfluxDB server clock are different, all requests are timestamped during
            # submission regardless of whether batching is enabled.
            timestamp = time.time()
        data_parts.append(str(InfluxDBDataLogger._timestamp(self.precision, timestamp)))
        data = " ".join(data_parts)

        self.logger.debug("InfluxDB: queue data=<%s>", data)
        self._queue.append(data)

        if len(self._queue) >= self._batch_size:
            try:
                authHeader = 'Token ' + self.token
                async with self.session.post(self.url, data="\n".join(self._queue), headers= {'Authorization': authHeader}) as response:
                    if response.status not in range(200, 300):
                        self.logger.error("InfluxDB: write status=%d body=%s",
                                          response.status, (await response.text()).strip())
                    self._queue.clear()
            except aiohttp.ClientError as error:
                self.logger.error("InfluxDB: http error=%s", str(error), exc_info=error)
                # don't clear queue on network error

    async def report_data(self, fields, timestamp=None):
        assert set(fields) == set(self.field_names)
        await self._report({"error": False, **fields}, timestamp)

    async def report_error(self, message, *args, exception=None, **kwargs):
        await super().report_error(message, *args, **kwargs, exception=exception)
        await self._report({"error": True})
