SPHINXOPTS  =
SPHINXBUILD = sphinx-build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help . _build $(SPHINXOPTS) $(O)

.PHONY: help Makefile

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ . _build $(SPHINXOPTS) $(O)
