# Contributing to Glasgow

## Contributing bug reports

Bug reports are always welcome! When reporting a bug, please include the following:

  * The operating system;
  * The version of Glasgow (use `glasgow --version`);
  * The complete debug log (use `glasgow -vvv [command...]`).

## Contributing code

Glasgow does not strictly adhere to any specific Python or C coding standards. If your code is structured and formatted similarly to existing code, it is good enough.

### Writing commit messages

When modifying Python code, the first line of a commit message should, if possible, start with the name of the module that is being modified, such that `git log --grep` can be easily used for filtering. E.g.:

    protocol.jtag_svf: accept and ignore whitespace in scan data.

When modifying firmware, the first line of a commit message should start with `firmware`. E.g.:

    firmware: fix an operator precedence issue.

When modifying schematics or layout, the first line of a commit message should start with the revision. E.g.:

    revC: swap U2/U3, fix DRC issue.

If none of the cases above are a good fit, any descriptive message is sufficient.
