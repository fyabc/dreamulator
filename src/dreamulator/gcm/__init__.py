"""GCM (ExoPlaSim) offline-oracle harness.

ExoPlaSim is used as an *offline* validation oracle for the heuristic climate
engine — never as a runtime engine in the build pipeline (see
``docs/design/proposals/climate-gcm-plan.md``).  This package is the thin
adapter between dreamulator world inputs and ExoPlaSim runs:

- :mod:`dreamulator.gcm.mapping` — pure world-input → ``Model.configure``
  parameter mapping (no ExoPlaSim import; unit-tested).
- :mod:`dreamulator.gcm.runner` — run orchestration, environment guard,
  manifest/provenance.
- :mod:`dreamulator.gcm.diagnostics` — NetCDF result summarisation.
- :mod:`dreamulator.gcm.plotting` — global overview figures.

The ``[gcm]`` optional dependency group installs ExoPlaSim and friends;
without it only :mod:`~dreamulator.gcm.mapping` is usable (and tested).
"""
