.. _docs:

Documentation
=============

The source files for this documentation manual is contained in the `GlasgowEmbedded/glasgow`_ repository under ``docs/manual/``. It is written in `reStructuredText`_ and published with `Sphinx`_, using `PDM`_ for package management.

To build the documentation locally, first `install PDM`_. Then, navigate to the working directory you have :ref:`installed <initial-setup>` the Glasgow software in, and run:

.. code:: console

    $ cd docs/manual
    $ pdm install

Once this step completes (which should always happen without errors), you are ready to edit the documentation. In a terminal, run:

.. code:: console

    $ pdm run live
    [sphinx-autobuild] > sphinx-build .../glasgow/docs/manual/src .../glasgow/docs/manual/out
    Running Sphinx v7.1.2
    loading pickled environment... done
    building [mo]: targets for 0 po files that are out of date
    writing output...
    building [html]: targets for 0 source files that are out of date
    updating environment: 0 added, 0 changed, 0 removed
    reading sources...
    looking for now-outdated files... none found
    no targets are out of date.
    build succeeded.

    The HTML pages are in out.
    [I 231002 04:16:58 server:335] Serving on http://127.0.0.1:8000
    [I 231002 04:16:58 handlers:62] Start watching changes
    [I 231002 04:16:58 handlers:64] Start detecting changes

This command starts a web server running on your local PC that allows you to quickly see any changes to the documentation you are making. Navigate to `the URL it prints <http://127.0.0.1:8000>`_, and open the page you would like to change. Whenever you edit the ``.rst`` file corresponding to the page, you should see the page automatically reload in the web browser, reflecting the new contents.

In some cases (primarily when you are updating the documentation index in the sidebar) the changes aren't picked up by the web server. In that case, remove the output directory to trigger a full rebuild.

The markup language we are using, reStructuredText, has an awkward syntax, and it is easy for new editors to introduce syntax changes. If this happens, the web server prints a warning message whenever the ``.rst`` file is saved. Watch out for these warnings---they can save a lot of time trying to understand why the markup does not render correctly.

To check that all of the external links in the documentation are valid, run the following command:

.. code:: console

    $ pdm check
    Running Sphinx v7.1.2
    [part of the output elided]

    (    develop/docs: line   37) ok        http://127.0.0.1:8000
    (        purchase: line   10) ok        https://1bitsquared.de/products/glasgow
    (        purchase: line    9) ok        https://1bitsquared.com/products/glasgow
    (       community: line   10) ok        https://1bitsquared.com/pages/chat
    (           intro: line   69) ok        https://asciinema.org/a/245309
    [... continued]

Our continuous integration system checks external links on every build, ensuring they stay valid.

.. _GlasgowEmbedded/glasgow: https://github.com/GlasgowEmbedded/glasgow
.. _reStructuredText: https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html
.. _Sphinx: https://www.sphinx-doc.org/en/master/index.html
.. _PDM: https://pdm-project.org/latest/
.. _install PDM: https://pdm-project.org/latest/#installation


Style guide
-----------

When writing documentation, please follow our style:

* Only capitalise the first word of headings.
* Insert two blank lines before headings.
* Use ``.. note::`` and ``.. warning::`` sparingly, where important details may otherwise be missed.
* Use an em-dash (---), which can be written as ``---`` in reStructuredText.
* Link to our `official repositories <https://github.com/GlasgowEmbedded>`_ where appropriate.
