"""The social layer (stage S3): author graphs per sub-window, clusters and lineages.

The framework locates communities from the network of researchers and their public acts (R1): co-authorship
and citation ties in sub-windows, clusters from at least two methods across a resolution sweep, and clusters
linked over time into lineages by overlap of membership. Only Leiden runs here; the hierarchical block model
needs graph-tool, which has no Windows build, so every output is provisional (decision D-1, 19 Sep 2026).
"""
