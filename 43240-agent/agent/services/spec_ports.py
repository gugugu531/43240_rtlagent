"""Supported scalar/flat unsigned ports for the controlled self-test renderer."""
import re
from agent.services.port_signature import port_signature


def _flat_signature(signature):
    if not signature:
        raise ValueError('unsupported or incomplete self-test port declaration')
    ports = []
    for name, direction, signed, packed, unpacked in signature:
        if (direction not in ('input', 'output') or signed or unpacked or len(packed) > 1
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name)):
            raise ValueError('self-test supports flat unsigned input/output ports only')
        if packed:
            upper, lower = packed[0]
            if lower != 0 or not 0 <= upper < 4096:
                raise ValueError('self-test vector range must be [width-1:0]')
            width = upper + 1
        else:
            width = 1
        ports.append((name, direction, width))
    return tuple(ports)


def supported_ports(task):
    spec = task.expected_interface
    if not spec.parsed or not spec.ports or spec.module_name != task.top:
        raise ValueError('unsupported or uncertain interface')
    ports = tuple((p.name, p.direction, p.width) for p in spec.ports)
    if (len({p[0] for p in ports}) != len(ports)
            or not any(p[1] == 'output' for p in ports)
            or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', n)
                   or d not in ('input', 'output') or type(w) is not int or not 1 <= w <= 4096
                   for n, d, w in ports)):
        raise ValueError('unsupported port name, direction or width')
    if task.interface.strip():
        signature = port_signature(task.interface + '\nendmodule', task.top)
        if _flat_signature(signature) != ports:
            raise ValueError('self-test interface declarations are incomplete or inconsistent')
    return ports


def validate_candidate_ports(source, top, plan):
    if top != plan.top or _flat_signature(port_signature(source, top)) != plan.ports:
        raise ValueError('self-test candidate interface does not match the supported plan ports')
