"""Guard against accidental experiments. Local policy is not tamper-proof security.

The delivered policy allows public collection and observation, NOT fabricated
market paths, hypothetical orders, model training, or live trading.
"""
from __future__ import annotations
import json
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[1] / 'runtime_policy.json'
SAFE = frozenset({'observation', 'public_collection', 'static_checks'})
RESTRICTED = frozenset({'backtest', 'training', 'paper', 'synthetic_market'})


def read_policy(path: Path | None = None) -> dict:
    p = path or POLICY_PATH
    if not p.exists():
        # Installed wheels without project policy must not silently unlock.
        return {'policy_version': 1, 'capabilities': {k: True for k in SAFE},
                'manual_authorization': None}
    value = json.loads(p.read_text(encoding='utf-8'))
    if value.get('policy_version') != 1 or not isinstance(value.get('capabilities'), dict):
        raise ValueError('Politique de permissions invalide.')
    return value


def check_permission(capability: str, policy: dict) -> None:
    if capability == 'live_orders':
        raise PermissionError('Aucun connecteur d’ordres réels : capacité interdite.')
    if capability not in SAFE | RESTRICTED:
        raise PermissionError('Capacité inconnue : refus par défaut.')
    if policy.get('capabilities', {}).get(capability) is not True:
        raise PermissionError(f'{capability}: non autorisé. Données réelles / observation seules actuellement.')
    if capability in RESTRICTED:
        auth = policy.get('manual_authorization')
        if not isinstance(auth, dict) or auth.get('ack') != 'AUTORISER_EXPERIENCES_HYPOTHETIQUES':
            raise PermissionError('Un nouvel accord explicite et journalisé est nécessaire.')
        if not auth.get('recorded_at_utc') or not auth.get('scope') or not auth.get('reviewer'):
            raise PermissionError('Autorisation incomplète.')
        if capability not in auth['scope']:
            raise PermissionError('Cette expérience dépasse le périmètre autorisé.')


def require_capability(capability: str) -> None:
    check_permission(capability, read_policy())
