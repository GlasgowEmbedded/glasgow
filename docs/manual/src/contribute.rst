Contributing
============

The Glasgow project relies on many community members to contribute to the extensive scope covered by its hardware and software. The project has a strong commitment to stability: most importantly, every unit of hardware for which design files have been published in the ``main`` branch will be supported forever. This scope and support commitment is challenging and requires us to be careful in evaluating any contributions.

We expect every contributor to work with the maintainers to ensure longevity of their contribution. If your contribution is substantial, please discuss it via our :ref:`community channels <community>` before working on it to ensure that it fits the project goals and to coordinate a long-term support commitment, especially in the cases where exotic or expensive hardware is required to test the changes.


.. _bug-reports:

Contributing bug reports
------------------------

Bug reports are always welcome! If you are experiencing an issue with your device and you are not sure what kind of issue it is, :ref:`ask the community for assistance <community>`.

For a timely resolution of your issues involving the Glasgow software, include the following information when `reporting a bug on GitHub <issues_>`__:

* The version of the Glasgow software stack and environment components (as printed by ``glasgow --version``);

* The complete debug information produced by the command you are running (as printed by ``glasgow -vvv [command...]``).

If you believe there is an issue with the design of the Glasgow hardware or firmware, `open an issue on GitHub <issues_>`__. The Glasgow hardware and firmware have been extensively reviewed, evaluated, and tested, and it is relatively unlikely for you to experience a design issue.

If you believe that your device may be damaged or malfunctioning, and the device is unmodified from the design files published in this repository (bearing the "Glasgow" name on it), you may :ref:`ask the community for assistance <community>` before referring to the manufacturer of your device. If your device has been :ref:`modified from the original design files <build>` or does not bear the "Glasgow" name on it, you must request assistance from the manufacturer of your device. You may ask the community for assistance if you make it clear in your request that your device has been modified from the original design files, but the effort required to evaluate such modifications is scarcely available.

.. _issues: https://github.com/GlasgowEmbedded/glasgow/issues/new


.. _contributing-code:
.. _contributing-docs:

Contributing code or documentation
----------------------------------

You are expected to contribute code as a `pull request <pulls_>`__ containing a small number of self-contained commits with :ref:`descriptive messages <commit-messages>`, each of which individually captures a functional state of the working tree. If your pull request does not fit this description it will not be merged until it is cleaned up, but it is okay to have a draft pull request containing a large number of temporary commits while it is undergoing review or ongoing work.

As Git is a notoriously difficult version control system to use effectively, feel free to :ref:`ask the community for assistance <community>`. Often, your pull request will be edited by maintainers to ensure it fits the codebase well. In those cases the maintainer will usually rearrange the commits to fit our requirements.

The Glasgow project does not strictly adhere to any specific Python or C coding standards. If your code is structured and formatted similarly to existing code, it is good enough. You may be instructed to reformat your code to ensure that it fits the codebase well.

.. _pulls: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests

.. _commit-messages:

Writing commit messages
#######################

When modifying Python code, the first line of a commit message should, if possible, start with the name of the module (not including the leading ``glasgow.``) that is being modified, such that ``git log --grep`` can be used to filter changes by scope:

.. code:: text

    protocol.jtag_svf: accept and ignore whitespace in scan data.

The format is the same for Python code implementing applets:

.. code:: text

    applet.interface.uart: make autobaud more reliable.

When modifying documentation, the first line of a commit message should start with ``manual:``, followed by the base name of the ``.rst`` file that is being modified:

.. code:: text

    manual: intro: update the list of applets.

When modifying firmware, the first line of a commit message should start with ``firmware:``:

.. code:: text

    firmware: fix an operator precedence issue.

If none of the cases above are a good fit, any descriptive message is sufficient.


.. _docs-archive:

Vendor documentation
####################

If you have used vendor documentation while writing the code you're contributing, you are required to:

* upload the documentation to the `Glasgow archive repository <archive_>`__; and

* reference the documentation at the top of the file in the following format:

  .. code:: text

      Ref: <insert vendor documentation title or, if impossible, any permanent-looking URL>
      Document Number: <insert vendor document number; omit the field if one does not exist>
      Accession: <insert Glasgow archive repository accession number>

If you cannot upload the documentation to the archive because it is under NDA and/or watermarked, :ref:`ask the community for assistance <community>`. Often, it is possible to collate enough information by using existing leaked documents or through parallel construction.

.. _archive: https://github.com/GlasgowEmbedded/archive
