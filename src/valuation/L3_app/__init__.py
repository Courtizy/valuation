"""L3 App: a static GitHub Pages site in site/ plus the tools that feed it.

publish.py copies pipeline outputs into site/data and writes the index the
page reads. demo.py makes a clearly labeled synthetic company for previews.
The site holds no valuation logic of its own except the projection what-if,
which is a tested port of core/projection.py.
"""
