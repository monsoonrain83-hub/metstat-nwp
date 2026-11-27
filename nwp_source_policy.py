"""Producer-first candidate policy for one model/product/forecast frame.

This module does not assert that unimplemented direct adapters are available.
Resolution priority is retained; official delivery wins within a resolution.
A whole derived product must be validated before fallback is considered.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    domain:str
    resolution:str
    tier:str
    producer:str
    licence:str

ECCC_LICENCE='ECCC Data Services End-use Licence v2.1.1; https://eccc-msc.github.io/open-data/licence/readme_en/'
ECCC_DOMAIN='msc_gdps_official'
PRODUCERS={
    'ecmwf':'ECMWF','gfs':'NOAA/NCEP','icon':'DWD','gem':'Environment and Climate Change Canada','ukmo':'UK Met Office',
    'aifs':'ECMWF','aigfs':'NOAA/NCEP','arpege':'Météo-France','jma':'JMA','cma':'CMA','kim':'KMA',
    'graphcast':'Google','weathernext':'Google',
}
# Only verified adapter capabilities are enabled. Other producer endpoints
# must be independently implemented/tested before their adapter is enabled.
OFFICIAL={'gem':Candidate(ECCC_DOMAIN,'15 km','producer',PRODUCERS['gem'],ECCC_LICENCE)}

def provenance(model,domain,official_report=None,attempted=False,reason=None):
    if model not in PRODUCERS:raise ValueError('unknown producer')
    if domain==ECCC_DOMAIN:
        if model!='gem' or not isinstance(official_report,dict) or not official_report:
            raise ValueError('official provenance requires verified field report')
        return dict(producer=PRODUCERS[model],distribution='producer',source_licence=ECCC_LICENCE,
                    attribution='Data Source: Environment and Climate Change Canada',
                    source_fields=official_report)
    if attempted and not reason:raise ValueError('fallback reason required')
    return dict(producer=PRODUCERS[model],distribution='intermediary',
                source_licence='Open-Meteo data; retain existing model-specific licence/attribution',
                fallback_reason=reason if attempted else 'official adapter not yet validated for this product',
                official_attempted=bool(attempted))
