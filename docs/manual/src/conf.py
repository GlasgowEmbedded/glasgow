html_title = project = "Glasgow Interface Explorer"
release = version = ""
copyright = "2020—2023, Glasgow Interface Explorer contributors"

extensions = [
    "sphinx.ext.todo",
    "sphinx_copybutton",
    "sphinx_inline_tabs",
]

todo_include_todos = True
todo_emit_warnings = True

copybutton_prompt_is_regexp = True
copybutton_prompt_text = r">>> |\.\.\. |\$ |> "
copybutton_copy_empty_lines = False

html_theme = "furo"
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
    "announcement": "The Early Bird units are being shipped by Mouser! <a href='https://crowdsupply.com/1bitsquared/glasgow'>Pre-Order yours now</a>",
}
html_use_modindex = False
html_use_index = False
