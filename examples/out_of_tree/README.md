# Example out-of-tree applet

Most applets currently reside in-tree (within the `glasgow` repository or its forks). On an **experimental** basis, support for out-of-tree applets is also provided. This feature is considered experimental because the Glasgow software does not provide a stable API.

To use this feature, first install the out-of-tree applet. With the recommended method of installation (pipx) this can be done with:

```console
$ pipx inject -e glasgow ./examples/out_of_tree
```

Once installed, the applet is runnable provided a special environment variable is set:

```console
$ export GLASGOW_OUT_OF_TREE_APPLETS=I-am-okay-with-breaking-changes
$ glasgow run exampleoot
W: g.support.plugin: loading out-of-tree plugin 'glasgowcontrib-applet-exampleoot'; plugin API is currently unstable and subject to change without warning
...
```

Note that there are no `glasgowcontrib/__init__.py` or `glasgowcontrib/applet/__init__.py` files included. This is intentional; `glasgowcontrib` and `glasgowcontrib.applet` are [PEP 420 namespace packages](https://peps.python.org/pep-0420/). Including such an `__init__` file by mistake will break every other out-of-tree applet, so take care.