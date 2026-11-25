# Source code, data and third-party licensing

GPLv3 applies to original MetStat NWP program source. Weather model inputs, analysis fields, climatology, observations and derived products remain subject to applicable provider terms. Review NOAA/NCEP, ECMWF, Environment and Climate Change Canada, DWD, UK Met Office and other providers individually; this notice does not claim a verified blanket data license. Python dependencies listed in requirements.txt and requirements-ecmwf.txt retain their own licenses; verify resolved versions and transitive dependencies before distributing a combined package. Use synthetic fixtures and do not include provider-restricted archives, credentials or private observations.

## Distribution checklist

- Preserve copyright and license notices for third-party components; do not claim rights the project does not own.
- Record source, version, license, modifications and attribution for redistributed material.
- Verify compatibility of the actual dependency graph and bundled assets; this document is not a completed legal audit.
- Provide the corresponding source and build instructions required by GPLv3 when distributing covered binaries.
- Keep private data and secrets separate from source; do not add non-GPL restrictions to GPL-covered code.
- Do not redistribute uncertain material until permission is established.
