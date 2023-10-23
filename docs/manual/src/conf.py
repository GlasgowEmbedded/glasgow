import os
is_production = True if os.getenv("DOCS_IS_PRODUCTION", "").lower() in ('1', 'yes', 'true') else False

html_title = project = "Glasgow Interface\u00a0Explorer"
release = version = ""
copyright = "2020—2023, Glasgow Interface Explorer contributors"

extensions = [
    "sphinx.ext.todo",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "sphinx_inline_tabs",
]

todo_include_todos = True
todo_emit_warnings = True

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

copybutton_prompt_is_regexp = True
copybutton_prompt_text = r">>> |\.\.\. |\$ |> "
copybutton_copy_empty_lines = False

html_use_modindex = False
html_use_index = False

html_theme = "furo"
html_baseurl = "https://glasgow-embedded.org/latest/"
html_css_files = [
      "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/fontawesome.min.css",
      "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/solid.min.css",
      "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/brands.min.css",
]
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
            "The Early Bird units are being shipped by Mouser! "
            "<a href='https://crowdsupply.com/1bitsquared/glasgow'>Pre-Order yours now</a>"
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
