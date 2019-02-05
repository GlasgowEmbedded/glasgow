#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os
import sphinx_rtd_theme

# Configure our load path
sys.path.insert(0, os.path.abspath('../software'))

# Configure Sphinx
extensions = ['sphinx.ext.viewcode', 'sphinx.ext.autodoc', 'sphinxarg.ext']
autodoc_member_order = 'bysource'
source_suffix = '.rst'
master_doc = 'index'
project = 'Glasgow Reference'
author = 'whitequark'
copyright = '2018-2019, whitequark'
pygments_style = 'sphinx'
html_theme = 'sphinx_rtd_theme'
