"""Recording-level proxy scoring using existing metadata match evidence.

An ISRC equality inherits upstream metadata-matching errors; it is not an
independently verified recording join. Unknown identities remain namespaced.
"""

import re

from .metrics import calculate_all_metrics


def recording_key(record, fallback):
    """Use a valid normalized ISRC; never conflate unknown cross-service IDs."""
    isrc = str(record.get('isrc') or '').replace('-', '').strip().upper()
    if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}\d{7}', isrc):
        return f'isrc:{isrc}'
    return fallback


def score_recordings(recommended, ground_truth, *, k=(1, 5, 10)):
    """Score unique recordings, padding shortages as misses at fixed capacity."""
    unique = list(dict.fromkeys(recommended))
    unique.extend(('missing', i) for i in range(max(k) - len(unique)))
    result = calculate_all_metrics(unique, ground_truth, k=list(k))
    result.pop('r_precision')  # retrieved prefixes do not cover the full R ranks
    return result
