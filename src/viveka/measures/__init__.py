"""The framework's instruments computed on in-memory inputs (spec §9).

Pure: no I/O, no clock, and randomness only through a ``numpy.random.Generator``
passed in by the caller. Every measure is oriented to the side the community
favours, so reversing a claim's registered orientation changes no value.
"""
