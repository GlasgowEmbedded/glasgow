# Contributing to Glasgow

## Contributing bug reports

Bug reports are always welcome! When reporting a bug, please include the following:

  * The operating system;
  * The version of Glasgow (use `glasgow --version`);
  * The complete debug log (use `glasgow -vvv [command...]`).

## Contributing code

Glasgow does not strictly adhere to any specific Python or C coding standards. If your code is structured and formatted similarly to existing code, it is good enough.

### Vendor documentation

If you have used vendor documentation while writing the code you're contributing, it is necessary to:

  * upload the documentation to the [Glasgow Archive][archive]; and
  * reference the documentation at the top of the file in the following format:

    ```
    Ref: <insert vendor documentation title or, if absent, URL here>
    Document Number: <insert vendor document number here, or omit the field if absent>
    Accession: <insert Glasgow Archive accession number here>
    ```

If you cannot upload the documentation to the archive because it is under NDA and/or watermarked, contact the maintainers for assistance. Often, it is possible to achieve sufficient coverage using techniques such as using existing leaked documents or parallel construction.

[archive]: https://github.com/GlasgowEmbedded/Glasgow-Archive

### Writing commit messages

When modifying Python code, the first line of a commit message should, if possible, start with the name of the module that is being modified, such that `git log --grep` can be easily used for filtering. E.g.:

    protocol.jtag_svf: accept and ignore whitespace in scan data.

When modifying firmware, the first line of a commit message should start with `firmware`. E.g.:

    firmware: fix an operator precedence issue.

When modifying schematics or layout, the first line of a commit message should start with the revision. E.g.:

    revC: swap U2/U3, fix DRC issue.

If none of the cases above are a good fit, any descriptive message is sufficient.
