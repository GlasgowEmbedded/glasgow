``sensor-sht4x``
================

Connect SCL and SDA to the selected Glasgow pins and share ground with the sensor. Pull SCL and SDA up to the sensor's supply voltage and configure the Glasgow I/O voltage to match. A bare SHT4x operates at 1.08–3.6 V.

The default I²C address is ``0x44``. If your part has a different factory-set address, select it with ``--i2c-address``. Both SHT40 and SHT43 have variants at ``0x45``, and some SHT40 variants use ``0x46``.

For example, with a 3.3 V sensor connected to A0 (SCL) and A1 (SDA), take one high-repeatability measurement:

.. code-block:: console

    $ glasgow run sensor-sht4x -V 3.3 --scl A0 --sda A1 measure

Normal measurements and logging do not activate the sensor's heater. Relative humidity is clipped to 0–100 %. Use ``log --interval 5`` to wait five seconds between samples instead of the default one second.

Heater operation
----------------

Use ``heat`` to pulse the heater once, for example to help clear condensation. The default is 20 mW for 0.1 s. Select a different pulse with ``--power`` (20, 110, or 200 mW nominal at 3.3 V) and ``--duration`` (0.1 or 1 s), after the ``heat`` subcommand. The sensor measures while the heater is still on, so the result is labeled as a heated sample and does not represent ambient conditions. Let the sensor cool before taking an ambient measurement.

Only use the heater below 65°C ambient. When repeating pulses, keep the heater duty cycle below 10%. The highest setting can draw about 75 mA, so use a supply that can handle the pulse without dropping voltage.

Each normal CLI invocation soft-resets only the sensor at the configured address before carrying out the requested operation. The addressed reset is also available through the interface in the REPL.

CLI reference
-------------

.. _applet.sensor.sht4x:

.. autoprogram:: glasgow.applet.sensor.sht4x:SensorSHT4xApplet._get_argparser_for_sphinx("sensor-sht4x")
    :prog: glasgow run sensor-sht4x


API reference
-------------

.. module:: glasgow.applet.sensor.sht4x

.. autoexception:: SHT4xError

.. autoclass:: SHT4xMeasurement

.. autoclass:: SHT4xI2CInterface
