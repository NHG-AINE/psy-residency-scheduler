"""Synthetic catalogue institutions for tests, independent of programme policy."""

INSTITUTIONS = {'R1': {'General Medicine': ('TTSH', 'SGH'),
        'Neurology': ('NNI', 'SGH'),
        'Medicine & Neurology': ('NUH',),
        'Inpatient Psychiatry': ('IMH', 'TTSH', 'CGH', 'SGH', 'NUH')},
 'R2': {'Geriatric Psychiatry': ('IMH', 'CGH', 'NUH', 'SGH'),
        'Child & Adolescent Psychiatry': ('IMH', 'NUH'),
        'Addiction Medicine': ('IMH',)},
 'R3': {'Continuity Clinic': ('IMH', 'TTSH', 'KTPH', 'WH', 'CGH', 'SGH', 'NUH', 'NTFGH', 'AH')},
 'R4': {'Inpatient Psychiatry': ('IMH', 'TTSH', 'CGH', 'SGH', 'NUH'),
        'Consultation Liaison Psychiatry': ('TTSH', 'KTPH', 'CGH', 'SGH', 'SKH', 'NUH', 'NTFGH'),
        'Emergency Psychiatry': ('IMH',),
        'Forensic Psychiatry': ('IMH',)},
 'R5': {'Geriatric Psychiatry': ('IMH', 'CGH', 'NUH'),
        'Child & Adolescent Psychiatry': ('IMH', 'NUH', 'KKH')}}

CORE_CATALOGUE = [
    {"residency_year": year, "posting": f"{site} {name}"}
    for year, postings in INSTITUTIONS.items()
    for name, institutions in postings.items()
    for site in institutions
]
