import sys, os, os.path
is_production = True if os.getenv("DOCS_IS_PRODUCTION", "").lower() in ('1', 'yes', 'true') else False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "software"))
import glasgow

# Otherwise on newer Python, `argparse` will render output using ANSI escape sequences, and they
# will get inserted into `sphinxcontrib.autoprogram` output.
os.environ["NO_COLOR"] = "1"

language = os.environ.get("DOCS_LANGUAGE", "en")
match language:
    case "en":
        project = "Glasgow Interface\u00a0Explorer"
        copyright = "2020—%Y, Glasgow Interface Explorer contributors"
        html_baseurl = "https://glasgow-embedded.org/en/"
    case "zh":
        project = "Glasgow 可重构数字接口调试器"
        copyright = "2020—%Y，Glasgow 可重构数字接口调试器贡献者"
        html_baseurl = "https://glasgow-embedded.cn/zh/"

# We don't do versioned releases.
release = version = ""

extensions = [
    "myst_parser",
    "sphinx.ext.todo",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_inline_tabs",
    "sphinxcontrib.autoprogram",
    "enum_tools.autoenum",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md":  "markdown",
}

highlight_language = "text"

rst_prolog = """
.. role:: py(code)
   :language: python
"""

autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
}
autodoc_preserve_defaults = True
autodoc_inherit_docstrings = False

napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_ivar = True
napoleon_include_init_with_doc = True
napoleon_include_special_with_doc = True

todo_include_todos = True
todo_emit_warnings = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", os.getenv("INTERSPHINX_PYTHON")),
}

copybutton_prompt_is_regexp = True
copybutton_prompt_text = r">>> |\.\.\. |\$ |> "
copybutton_copy_empty_lines = False

locale_dirs = ["../locale/"]
gettext_compact = False

templates_path = ["_templates/"]

html_use_modindex = False
html_use_index = False

html_title = project
html_theme = "furo"
html_static_path = ["_static"]
html_css_files = [
      "font-awesome/css/fontawesome.min.css",
      "font-awesome/css/solid.min.css",
      "font-awesome/css/brands.min.css",
      "styles/custom.css",
]
html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/scroll-end.html",
        "sidebar/variant-selector.html",
        "sidebar/language-selector.html",
    ],
}
html_context = {
    "languages": {
        "en": "English",
        "zh": "汉语",
    },
}
html_theme_options = {
    "top_of_page_button": "edit",
    "source_repository": "https://github.com/GlasgowEmbedded/glasgow/",
    "source_branch": "main",
    "source_directory": "docs/manual/src/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/GlasgowEmbedded/glasgow/",
            "html": "",
            "class": "fa-brands fa-solid fa-github fa-2x",
        },
    ],
}
if is_production:
    html_theme_options.update({
        "light_css_variables": {
            "color-announcement-background": "#56bf62",
            "color-announcement-text": "#094a05",
        },
        "dark_css_variables": {
            "color-announcement-background": "#1c4808",
            "color-announcement-text": "#64cc69",
        },
        "announcement":
            "The latest revision, revD, is in pre-launch phase on CrowdSupply. "
            "<a href='https://www.crowdsupply.com/fully-automated/glasgow-interface-explorer-revd'>Subscribe now!</a>"
    })
else:
    html_theme_options.update({
        "light_css_variables": {
            "color-announcement-background": "#ffdf76",
            "color-announcement-text": "#664e04",
        },
        "dark_css_variables": {
            "color-announcement-background": "#604b2b",
            "color-announcement-text": "#eee388",
        },
        "announcement":
            "This documentation page has been built as a preview. It may be outdated or incorrect "
            "compared to <a href='https://glasgow-embedded.org/'>the official version</a>."
    })

linkcheck_ignore = [
    r"^http://127\.0\.0\.1:8000$",
    # Doesn't like the linkcheck User-Agent.
    r"^https://mouser\.com/",
    # For unknown reasons, these are (mostly) unreachable from GitHub CI runners.
    r"^https://chaos\.social/",
    r"^https://en\.uesp\.net/",
    r"^https://www\.gnu\.org/",
    r"^https://sdcc\.sourceforge\.net/",
    # Part of applet option help.
    r"^tcp:",
]

linkcheck_anchors_ignore_for_url = [
    r"^https://matrix\.to/",
    r"^https://web\.libera\.chat/",
    # GitHub is a React-based SPA; even README content is included as a JSON payload.
    r"^https://github\.com/",
]

# Attempt to keep linkcheck times manageable.
linkcheck_retries = 5
linkcheck_timeout = 5
linkcheck_workers = 50
