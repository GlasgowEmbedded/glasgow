import unittest

from glasgow.support.lazy import lazy


class _test:
    pass


class LazyTestCase(unittest.TestCase):
    def test_get(self):
        x = _test()
        x.f = 0
        y = lazy(lambda: x)
        x.f = 1
        self.assertEqual(y.f, 1)

    def test_set(self):
        x = _test()
        x.f = 0
        y = lazy(lambda: x)
        y.f = 1
        self.assertEqual(x.f, 1)

    def test_del(self):
        x = _test()
        x.f = 0
        y = lazy(lambda: x)
        del y.f
        with self.assertRaises(AttributeError):
            x.f

    def test_str(self):
        x = lazy(lambda: "foo")
        self.assertEqual(str(x), "foo")

    def test_repr(self):
        x = lazy(lambda: "foo")
        self.assertTrue(repr(x).startswith("<lazy <function"))
        str(x)
        self.assertTrue(repr(x).startswith("<lazy 'foo'"))
