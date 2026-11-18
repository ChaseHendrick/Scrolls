"""Synchronised, correctness-gated timing of a reference and a candidate implementation.

A speed number from this module exists only for a candidate whose output matched the reference's
under a stated rule (bitwise, exact value, or atol and rtol), whose control output failed that same
rule, and whose output still matched after timing. Otherwise the receipt carries a refusal status
and no speedup at all, and a wrong candidate is never timed.

- ``benchmark(reference, candidate, ...)`` runs the gate, then times both arms in ABBA order with
  a device sync before every clock read, and returns the receipt (a JSON-ready dict).
- ``time_callable(fn, ...)`` times one callable the same way, with no correctness claim;
  ``timing_receipt`` wraps such timings in a receipt that has no speedup keys, for tools whose
  variants differ by design.
- ``compare_outputs`` walks nested dicts, lists and tuples of tensors, arrays and Python scalars
  and fails closed on any difference of type, shape, dtype or value.
- ``write_receipt`` and ``check_receipt`` store and re-check a receipt; ``environment`` and
  ``git_state`` say where and from which code it came.

Standard library at import time. numpy and torch are looked up in ``sys.modules`` when a leaf of
that type appears, so no import is forced, and torch is imported only for a device other than the
CPU. Device synchronisation is kit/accel.py's ``synchronize``, imported only for a
device other than the CPU; this module does not reimplement it.
"""
import copy
import datetime
import functools
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import pathlib
import platform
import statistics
import struct
import subprocess
import sys
import tempfile
import time

SCHEMA = 1
KIND = 'kit-accelbench'
MIN_REPEATS = 5
DEFAULT_WARMUP = 3
DEFAULT_REPEATS = 7
STATUSES = ('pass', 'refused-mismatch', 'refused-unstable', 'invalid-control', 'timing-only')
SPEEDUP_KEYS = ('speedup', 'speedup_median', 'speedup_paired_median')
ROOT = pathlib.Path(__file__).resolve().parent.parent
_MAX_PATHS = 32
_RELATIVE = 1e-12


# Devices and synchronisation.

class DeviceSync:
    """A zero-argument device sync that says what it waits on, for the receipt."""
    __slots__ = ('_fn', 'description')

    def __init__(self, fn, description):
        self._fn = fn
        self.description = description

    def __call__(self):
        self._fn()

    def __repr__(self):
        return f'DeviceSync({self.description})'


def _noop():
    return None


def _device_name(device):
    if device is None:
        raise ValueError('device is required (cpu, cuda, cuda:N or mps)')
    name = str(device).strip().lower()
    if not name:
        raise ValueError('device is empty')
    if name == 'auto':
        raise ValueError("resolve 'auto' first (kit.accel.resolve_device), so the receipt names the device")
    return name


def _device_type(name):
    return name.split(':', 1)[0]


def sync_for(device='cpu'):
    """The sync to run before every clock read on ``device``.

    cpu: a no-op, without importing torch. Any other device: a callable that runs
    ``kit.accel.synchronize(device)`` after ``kit.accel.resolve_device`` accepted the device.
    Raises ValueError when kit/accel.py or torch is missing, when this torch cannot use
    the device, or when kit.accel has no sync for its type, so an accelerator never gets a silent
    no-op and torch's own errors never leak."""
    name = _device_name(device)
    if _device_type(name) == 'cpu':
        return DeviceSync(_noop, 'none (cpu)')
    try:
        accel = importlib.import_module('kit.accel')
    except ImportError as error:
        raise ValueError(f'device {name!r} needs kit/accel.py for its synchronisation; '
                         f'only cpu works without it') from error
    try:
        resolved = str(accel.resolve_device(name))
        kind = accel.device_type(resolved)
    except ImportError as error:
        raise ValueError(f'device {name!r} needs torch') from error
    except (RuntimeError, AssertionError, AttributeError, TypeError) as error:
        raise ValueError(f'device {name!r}: {error}') from error
    if kind not in ('cuda', 'mps'):
        raise ValueError(f'no synchronisation known for device {name!r}: kit.accel.synchronize waits only '
                         f'on cuda and mps')
    return DeviceSync(functools.partial(accel.synchronize, resolved), f'kit.accel.synchronize({resolved})')


def _resolve_sync(name, sync):
    if sync is None:
        return sync_for(name)
    if not callable(sync):
        raise ValueError('sync must be a zero-argument callable or None')
    return sync


def _qualname(obj):
    if isinstance(obj, functools.partial):
        return f'functools.partial({_qualname(obj.func)})'
    module = getattr(obj, '__module__', None)
    qual = getattr(obj, '__qualname__', None)
    if not isinstance(qual, str):
        module, qual = type(obj).__module__, type(obj).__qualname__
    return f'{module}.{qual}' if module else qual


def _sync_description(sync):
    description = getattr(sync, 'description', None)
    return description if isinstance(description, str) else _qualname(sync)


# Timing.

def _check_counts(warmup, repeats, number):
    for label, value in (('warmup', warmup), ('repeats', repeats), ('number', number)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{label} must be an int, got {value!r}')
    if repeats < MIN_REPEATS:
        raise ValueError(f'repeats must be at least {MIN_REPEATS}, got {repeats}')
    if warmup < 0:
        raise ValueError(f'warmup must be at least 0, got {warmup}')
    if number < 1:
        raise ValueError(f'number must be at least 1, got {number}')


def _inputs(setup, args, kwargs):
    if setup is None:
        return tuple(args), dict(kwargs or {})
    made = setup()
    if not isinstance(made, (tuple, list)) or len(made) != 2:
        raise ValueError('setup() must return (args, kwargs)')
    a, k = made
    return tuple(a), dict(k or {})


def _sample(fn, args, kwargs, number, clock, sync):
    """One timed sample: sync, read the clock, ``number`` calls, sync, read the clock."""
    out = None
    sync()
    t0 = clock()
    for _ in range(number):
        out = fn(*args, **kwargs)
    sync()
    t1 = clock()
    return (t1 - t0) / number, out


def _finite_or_none(value):
    return value if isinstance(value, float) and math.isfinite(value) else None


def _ratio(a, b):
    if a is None or b is None or not b:
        return None
    return _finite_or_none(float(a) / float(b))


def _summary(seconds, warmup, repeats, number, clock, sync):
    seconds = [float(s) for s in seconds]
    low, high = min(seconds), max(seconds)
    median = statistics.median(seconds)
    return {'seconds': seconds, 'min_s': low, 'median_s': median, 'mean_s': statistics.fmean(seconds),
            'max_s': high, 'spread': _ratio(high - low, median), 'warmup': warmup, 'repeats': repeats,
            'number': number, 'clock': _qualname(clock), 'sync': _sync_description(sync)}


def time_callable(fn, *, args=(), kwargs=None, setup=None, device='cpu', warmup=DEFAULT_WARMUP,
                  repeats=DEFAULT_REPEATS, number=1, clock=time.perf_counter, sync=None):
    """Time ``fn`` with a device sync before every clock read; no correctness claim.

    setup: optional zero-argument callable returning (args, kwargs), called outside the timed region
    before each warm-up call and each sample, for functions that change their inputs (with
    number > 1 the calls of one sample share one setup). Returns the per-call seconds in run order
    and their min, median, mean, max and spread ((max - min) / median)."""
    _check_counts(warmup, repeats, number)
    sync = _resolve_sync(_device_name(device), sync)
    for _ in range(warmup):
        a, k = _inputs(setup, args, kwargs)
        fn(*a, **k)
        sync()
    seconds = []
    for _ in range(repeats):
        a, k = _inputs(setup, args, kwargs)
        seconds.append(_sample(fn, a, k, number, clock, sync)[0])
    return _summary(seconds, warmup, repeats, number, clock, sync)


# Output comparison.

def _rule(atol, rtol, bitwise, equal_nan, check_dtype):
    for label, value in (('atol', atol), ('rtol', rtol)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{label} must be a number, got {value!r}')
        if not math.isfinite(value) or value < 0:
            raise ValueError(f'{label} must be finite and at least 0, got {value!r}')
    if bitwise and (atol or rtol):
        raise ValueError('bitwise comparison takes no tolerance; set atol = rtol = 0')
    return {'atol': float(atol), 'rtol': float(rtol), 'bitwise': bool(bitwise), 'equal_nan': bool(equal_nan),
            'check_dtype': bool(check_dtype)}


def _module(name):
    return sys.modules.get(name)


def _numpy():
    return _module('numpy') or importlib.import_module('numpy')


def _is_tensor(x):
    torch = _module('torch')
    tensor = getattr(torch, 'Tensor', None) if torch is not None else None
    return isinstance(tensor, type) and isinstance(x, tensor)


def _is_ndarray(x):
    np = _module('numpy')
    return np is not None and isinstance(x, np.ndarray)


def _is_npscalar(x):
    np = _module('numpy')
    return np is not None and isinstance(x, np.generic)


_SCALARS = (bool, int, float, complex, str, bytes, type(None))
_INT_VIEW = {1: 'uint8', 2: 'int16', 4: 'int32', 8: 'int64'}


def _category(x):
    if _is_tensor(x):
        return 'tensor'
    if _is_ndarray(x):
        return 'ndarray'
    if _is_npscalar(x):
        return 'numpy scalar'
    if type(x) in _SCALARS:
        return type(x).__name__
    if isinstance(x, dict):
        return 'dict'
    if isinstance(x, list):
        return 'list'
    if isinstance(x, tuple):
        return 'tuple'
    return None


def _tensor_array(t):
    """(values, bits, dtype name) for a tensor; strides, layout and device are ignored. bits is None
    when numpy has the dtype (the values array then holds the bits too)."""
    torch = _module('torch')
    _numpy()                                   # Tensor.numpy() needs numpy, which torch may not have loaded
    t = t.detach()
    if t.layout != torch.strided:
        t = t.to_dense()
    t = t.cpu().resolve_conj().resolve_neg().contiguous()
    name = str(t.dtype)
    try:
        return t.numpy(), None, name
    except (TypeError, RuntimeError):
        pass
    # A dtype numpy lacks (bfloat16, the float8 types): values through float64 (or complex128), which
    # holds every such value exactly, and bits through a same-size integer view.
    target = torch.complex128 if t.is_complex() else torch.float64
    bits = t.view(getattr(torch, _INT_VIEW[t.element_size()])).numpy()
    return t.to(target).numpy(), bits, name


def _leaf_array(x, category):
    if category == 'tensor':
        return _tensor_array(x)
    array = _numpy().asarray(x)
    return array, None, str(array.dtype)


class _Walk:
    def __init__(self, rule, max_reported):
        self.rule = rule
        self.max_reported = max_reported
        self.leaves = 0
        self.different_leaves = 0
        self.different_elements = 0
        self.max_abs = None
        self.max_rel = None
        self.differences = []

    def note(self, abs_diff, rel_diff):
        if abs_diff is not None and math.isfinite(abs_diff):
            self.max_abs = abs_diff if self.max_abs is None else max(self.max_abs, abs_diff)
        if rel_diff is not None and math.isfinite(rel_diff):
            self.max_rel = rel_diff if self.max_rel is None else max(self.max_rel, rel_diff)

    def differ(self, path, kind, elements=1, abs_diff=None):
        self.different_leaves += 1
        self.different_elements += int(elements)
        if len(self.differences) < self.max_reported:
            self.differences.append({'path': path, 'kind': kind, 'elements': int(elements),
                                     'max_abs_diff': _finite_or_none(abs_diff)})

    def walk(self, a, b, path):
        ca, cb = _category(a), _category(b)
        if ca in ('dict', 'list', 'tuple') or cb in ('dict', 'list', 'tuple'):
            return self.container(a, b, ca, cb, path)
        self.leaves += 1
        if ca is None or cb is None:
            return self.differ(path, f'unsupported type {type(a).__name__ if ca is None else type(b).__name__}')
        if ca != cb or (ca not in ('tensor', 'ndarray', 'numpy scalar') and type(a) is not type(b)):
            return self.differ(path, f'leaf type {ca} against {cb}')
        if ca in ('tensor', 'ndarray', 'numpy scalar'):
            return self.array(a, b, ca, path)
        return self.scalar(a, b, path)

    def container(self, a, b, ca, cb, path):
        if ca != cb or type(a) is not type(b):
            self.leaves += 1
            return self.differ(path, f'container type {type(a).__name__} against {type(b).__name__}')
        if ca == 'dict':
            if a.keys() != b.keys():
                missing = [k for k in a if k not in b]
                extra = [k for k in b if k not in a]
                self.differ(path, 'mapping keys', len(missing) + len(extra))
            for key in a:
                if key in b:
                    self.walk(a[key], b[key], f'{path}[{key!r}]')
            return None
        if len(a) != len(b):
            self.differ(path, f'sequence length {len(a)} against {len(b)}', abs(len(a) - len(b)))
        for index, (x, y) in enumerate(zip(a, b)):
            self.walk(x, y, f'{path}[{index}]')
        return None

    def scalar(self, a, b, path):
        rule = self.rule
        if isinstance(a, int):                                     # bool too: always exact
            try:
                diff = float(abs(int(a) - int(b)))
            except OverflowError:
                diff = None
            self.note(diff, None)
            if a != b:
                self.differ(path, 'value', 1, diff)
            return None
        if isinstance(a, (float, complex)):
            finite = _scalar_finite(a) and _scalar_finite(b)
            diff = abs(b - a) if finite else None
            self.note(diff, diff / abs(a) if finite and a != 0 else None)
            if rule['bitwise']:
                same = _scalar_bits(a) == _scalar_bits(b)
            else:
                same = _scalar_ok(a, b, rule)
            if not same:
                self.differ(path, 'bits' if rule['bitwise'] else 'value', 1, diff)
            return None
        if a != b:
            self.differ(path, 'value')
        return None

    def array(self, a, b, category, path):
        np = _numpy()
        rule = self.rule
        try:
            ra, bits_a, name_a = _leaf_array(a, category)
            rb, bits_b, name_b = _leaf_array(b, category)
        except Exception as error:                                      # noqa: BLE001  fail closed
            return self.differ(path, f'unreadable leaf ({type(error).__name__}: {error})')
        if ra.shape != rb.shape:
            return self.differ(path, f'shape {list(ra.shape)} against {list(rb.shape)}')
        if (rule['check_dtype'] or rule['bitwise']) and name_a != name_b:
            return self.differ(path, f'dtype {name_a} against {name_b}')
        if 'O' in (ra.dtype.kind, rb.dtype.kind):
            return self.differ(path, 'unsupported dtype object')
        numeric = ra.dtype.kind in 'biufc' and rb.dtype.kind in 'biufc'
        with np.errstate(all='ignore'):
            if numeric:
                self.array_diagnostics(ra, rb, np)
            if rule['bitwise']:
                bad = _bits_differ(ra if bits_a is None else bits_a, rb if bits_b is None else bits_b, np)
            elif not numeric:
                bad = _bits_differ(ra, rb, np) if ra.dtype == rb.dtype else _not_equal(ra, rb, np)
            elif ra.dtype.kind in 'fc' or rb.dtype.kind in 'fc':
                if ra.dtype.kind in 'biu' or rb.dtype.kind in 'biu':
                    bad = _not_equal(ra, rb, np)                     # an integer or bool side: exact
                else:
                    bad = ~_values_ok(ra, rb, rule, np)
            else:
                bad = _not_equal(ra, rb, np)                         # integer and bool leaves: exact
            count = int(np.count_nonzero(bad))
            if count:
                diff = None
                if numeric:
                    wide = _wide(ra, rb, np)
                    d = np.abs(rb[bad].astype(wide) - ra[bad].astype(wide))
                    d = d[np.isfinite(d)]
                    diff = float(d.max()) if d.size else None
                self.differ(path, 'bits' if rule['bitwise'] else 'values', count, diff)
        return None

    def array_diagnostics(self, ra, rb, np):
        if not ra.size:
            return
        wide = _wide(ra, rb, np)
        r, c = ra.astype(wide), rb.astype(wide)
        finite = np.isfinite(r) & np.isfinite(c)
        if not finite.any():
            return
        d = np.abs(c[finite] - r[finite])
        mag = np.abs(r[finite])
        rel = d[mag > 0] / mag[mag > 0]
        self.note(float(d.max()), float(rel.max()) if rel.size else None)


def _wide(ra, rb, np):
    return np.complex128 if 'c' in (ra.dtype.kind, rb.dtype.kind) else np.float64


def _scalar_finite(x):
    if isinstance(x, complex):
        return math.isfinite(x.real) and math.isfinite(x.imag)
    return math.isfinite(x)


def _scalar_nan(x):
    if isinstance(x, complex):
        return math.isnan(x.real) or math.isnan(x.imag)
    return math.isnan(x)


def _scalar_bits(x):
    if isinstance(x, complex):
        return struct.pack('<dd', x.real, x.imag)
    return struct.pack('<d', x)


def _scalar_ok(r, c, rule):
    if _scalar_nan(r) or _scalar_nan(c):
        return rule['equal_nan'] and _scalar_nan(r) and _scalar_nan(c)
    if not (_scalar_finite(r) and _scalar_finite(c)):
        return r == c
    return abs(c - r) <= rule['atol'] + rule['rtol'] * abs(r)


def _values_ok(ra, rb, rule, np):
    """Elementwise: abs(c - r) <= atol + rtol * abs(r); infinities exact; NaN only with equal_nan."""
    wide = np.promote_types(np.promote_types(ra.dtype, rb.dtype), np.float64)
    r, c = ra.astype(wide), rb.astype(wide)
    finite = np.isfinite(r) & np.isfinite(c)
    ok = np.zeros(r.shape, dtype=bool)
    ok[finite] = np.abs(c[finite] - r[finite]) <= rule['atol'] + rule['rtol'] * np.abs(r[finite])
    rest = ~finite
    if rest.any():
        nan_r, nan_c = np.isnan(r), np.isnan(c)
        same = ~nan_r & ~nan_c & (r == c)
        if rule['equal_nan']:
            same |= nan_r & nan_c
        ok |= rest & same
    return ok


def _not_equal(ra, rb, np):
    try:
        bad = np.asarray(ra != rb)
    except (TypeError, ValueError):
        bad = None
    return bad if bad is not None and bad.shape == ra.shape else np.ones(ra.shape, dtype=bool)


def _bits_differ(ra, rb, np):
    """Per element: do the stored bytes differ (0.0 and -0.0 differ, equal NaN bits match)."""
    if ra.dtype != rb.dtype or ra.dtype.itemsize == 0:
        return np.ones(ra.shape, dtype=bool) if ra.dtype != rb.dtype else np.zeros(ra.shape, dtype=bool)
    size = ra.dtype.itemsize
    ba = np.ascontiguousarray(ra).view(np.uint8).reshape(ra.size, size)
    bb = np.ascontiguousarray(rb).view(np.uint8).reshape(rb.size, size)
    return (ba != bb).any(axis=1).reshape(ra.shape)


def compare_outputs(reference, candidate, *, atol=0.0, rtol=0.0, bitwise=False, equal_nan=False,
                    check_dtype=True, max_reported=32):
    """Compare two outputs leaf by leaf and fail closed.

    Containers: dicts need the same keys, lists and tuples the same type and length. Leaves: torch
    tensors (detached and moved to the CPU; strides and layout ignored), numpy arrays and scalars,
    and Python int, float, complex, bool, str, bytes and None; anything else is a difference. A leaf
    pair needs the same leaf type (a tensor never equals an array), the same shape, and the same
    dtype when check_dtype (always with bitwise). bitwise: identical bytes, so 0.0 and -0.0 differ
    and identical NaN bits match. Otherwise abs(c - r) <= atol + rtol * abs(r) for every element,
    r from the reference; infinities must match exactly; NaN fails unless equal_nan and both are
    NaN; integer and bool leaves are always exact. With atol = rtol = 0 that is exact value
    equality."""
    rule = _rule(atol, rtol, bitwise, equal_nan, check_dtype)
    if isinstance(max_reported, bool) or not isinstance(max_reported, int) or max_reported < 0:
        raise ValueError(f'max_reported must be an int of at least 0, got {max_reported!r}')
    walk = _Walk(rule, max_reported)
    walk.walk(reference, candidate, 'output')
    return {'pass': walk.different_leaves == 0, 'rule': rule, 'leaves': walk.leaves,
            'different_leaves': walk.different_leaves, 'different_elements': walk.different_elements,
            'max_abs_diff': _finite_or_none(walk.max_abs), 'max_rel_diff': _finite_or_none(walk.max_rel),
            'differences': walk.differences}


# The control: the reference output moved just past the rule.

def _numeric_leaves(x, path=()):
    """(path, 'float' | 'int' | 'bool') for each leaf with at least one element, in walk order."""
    category = _category(x)
    if category == 'dict':
        for key, value in x.items():
            yield from _numeric_leaves(value, path + (key,))
    elif category in ('list', 'tuple'):
        for index, value in enumerate(x):
            yield from _numeric_leaves(value, path + (index,))
    elif category in ('bool', 'int'):
        yield path, category
    elif category in ('float', 'complex'):
        yield path, 'float'
    elif category in ('ndarray', 'numpy scalar'):
        array = _module('numpy').asarray(x)
        kind = array.dtype.kind
        if array.size:
            if kind == 'b':
                yield path, 'bool'
            elif kind in 'iu':
                yield path, 'int'
            elif kind in 'fc':
                yield path, 'float'
    elif category == 'tensor' and x.numel():
        torch = _module('torch')
        if x.is_floating_point() or x.is_complex():
            yield path, 'float'
        elif x.dtype == torch.bool:
            yield path, 'bool'
        else:
            try:
                torch.iinfo(x.dtype)
            except (TypeError, RuntimeError, ValueError):
                return
            yield path, 'int'


def _replace(x, path, fn):
    """A copy of x along ``path`` with the leaf there replaced by fn(leaf); other leaves are shared."""
    if not path:
        return fn(x)
    key, rest = path[0], path[1:]
    if isinstance(x, tuple):
        items = list(x)
        items[key] = _replace(x[key], rest, fn)
        return type(x)(*items) if hasattr(type(x), '_fields') else type(x)(items)
    y = copy.copy(x)
    y[key] = _replace(x[key], rest, fn)
    return y


def _moved_value(x, atol, rtol, cast):
    """A value above x, stored in x's dtype through ``cast``, that the value rule rejects against x:
    first x + 2 * (atol + rtol * abs(x)), then doubling the step until the stored value moves."""
    limit = atol + rtol * abs(x)
    step = 2 * limit if limit > 0 else max(abs(x) * 2.0 ** -60, 2.0 ** -160)
    for _ in range(4096):
        y = cast(x + step)
        if not math.isfinite(y) or abs(y - x) > limit:
            return y
        step *= 2
    raise ValueError(f'could not move {x!r} past the rule')


def _perturb_float(x, atol, rtol, cast):
    if isinstance(x, complex):
        if not _scalar_finite(x):
            return complex(0.0, 0.0)
        return complex(_moved_value(x.real, atol, rtol, cast), x.imag)
    if not math.isfinite(x):
        return 0.0
    return _moved_value(x, atol, rtol, cast)


def _perturb_leaf(x, kind, atol, rtol):
    category = _category(x)
    if category in ('bool', 'int', 'float', 'complex'):
        if kind == 'bool':
            return not x
        if kind == 'int':
            return x + 1
        return type(x)(_perturb_float(x, atol, rtol, float))
    if category in ('ndarray', 'numpy scalar'):
        np = _module('numpy')
        array = np.array(x, copy=True, order='C')
        flat = array.reshape(-1)
        index = 0
        if kind == 'bool':
            flat[0] = not bool(flat[0])
        elif kind == 'int':
            info = np.iinfo(array.dtype)
            value = int(flat[0])
            flat[0] = value + 1 if value < info.max else value - 1
        else:
            finite = np.flatnonzero(np.isfinite(flat))
            index = int(finite[0]) if finite.size else 0
            real = np.dtype(array.real.dtype)

            def cast(v, real=real):
                with np.errstate(all='ignore'):
                    return float(np.array(v, dtype=np.float64).astype(real))
            value = flat[index].item()
            flat[index] = _perturb_float(value, atol, rtol, cast) if finite.size else 0
        return array if category == 'ndarray' else array[()]
    torch = _module('torch')
    tensor = x.detach().clone(memory_format=torch.contiguous_format)
    flat = tensor.reshape(-1)
    if kind == 'bool':
        flat[0] = not bool(flat[0])
    elif kind == 'int':
        info = torch.iinfo(tensor.dtype)
        value = int(flat[0])
        flat[0] = value + 1 if value < info.max else value - 1
    else:
        finite = torch.isfinite(flat).nonzero()
        index = int(finite[0, 0]) if finite.numel() else 0
        real = tensor.real.dtype if tensor.is_complex() else tensor.dtype

        def cast(v, real=real):
            return float(torch.tensor(v, dtype=torch.float64).to(real))
        flat[index] = _perturb_float(flat[index].item(), atol, rtol, cast) if finite.numel() else 0
    return tensor


def _perturb(reference_output, atol=0.0, rtol=0.0):
    """The reference output with one element moved past the rule: the first float leaf's first finite
    element by 2 * (atol + rtol * abs(x)) or more (a non-finite-only leaf gets a 0), else one int
    element by 1, else one bool flipped. Only the path to that element is copied. Raises
    ValueError when the output has no numeric leaf."""
    found = {}
    for path, kind in _numeric_leaves(reference_output):
        found.setdefault(kind, path)
    for kind in ('float', 'int', 'bool'):
        if kind in found:
            return _replace(reference_output, found[kind],
                            lambda leaf, kind=kind: _perturb_leaf(leaf, kind, float(atol), float(rtol)))
    raise ValueError('the output has no numeric leaf to perturb; pass control=None or a callable')


def _clone(x):
    """A deep copy that detaches tensors (deepcopy refuses non-leaf tensors)."""
    category = _category(x)
    if category == 'tensor':
        return x.detach().clone()
    if category == 'ndarray':
        return x.copy()
    if category == 'dict':
        y = copy.copy(x)
        for key in list(y):
            y[key] = _clone(x[key])
        return y
    if category == 'list':
        y = copy.copy(x)
        y[:] = [_clone(v) for v in x]
        return y
    if category == 'tuple':
        items = [_clone(v) for v in x]
        return type(x)(*items) if hasattr(type(x), '_fields') else type(x)(items)
    return copy.deepcopy(x)


# Descriptions for the receipt.

def _describe(x, depth=0):
    category = _category(x)
    if depth > 8:
        return {'type': 'deeper'}
    if category == 'tensor':
        return {'type': 'tensor', 'shape': list(x.shape), 'dtype': str(x.dtype), 'device': str(x.device)}
    if category == 'ndarray':
        return {'type': 'ndarray', 'shape': list(x.shape), 'dtype': str(x.dtype)}
    if category == 'numpy scalar':
        return {'type': 'numpy scalar', 'dtype': str(x.dtype)}
    if category == 'dict':
        items = list(x.items())
        out = {'type': 'dict', 'length': len(items),
               'items': {str(k): _describe(v, depth + 1) for k, v in items[:_MAX_PATHS]}}
        return out
    if category in ('list', 'tuple'):
        return {'type': type(x).__name__, 'length': len(x), 'items': [_describe(v, depth + 1) for v in x[:16]]}
    if category in ('str', 'bytes'):
        return {'type': category, 'length': len(x)}
    if category is not None:
        return {'type': category}
    return {'type': _qualname(type(x))}


def _first_float_dtype(x, depth=0):
    category = _category(x)
    if depth > 8:
        return None
    if category == 'dict':
        x = list(x.values())
        category = 'list'
    if category in ('list', 'tuple'):
        for value in x:
            found = _first_float_dtype(value, depth + 1)
            if found:
                return found
        return None
    if category == 'tensor' and x.is_floating_point():
        return str(x.dtype)
    if category in ('ndarray', 'numpy scalar') and x.dtype.kind == 'f':
        return str(x.dtype)
    if category == 'float':
        return 'float'
    return None


def _processor():
    cpuinfo = pathlib.Path('/proc/cpuinfo')
    try:
        if cpuinfo.is_file():
            for line in cpuinfo.read_text(errors='replace').splitlines():
                if line.startswith('model name'):
                    return line.split(':', 1)[1].strip()
        if platform.system() == 'Darwin':                      # Untested idea: not yet run on a Mac
            out = subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True,
                                 timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.machine() or None


def _attempt(fn):
    try:
        return fn()
    except Exception:                                             # noqa: BLE001  a report, never a failure
        return None


def environment(device='cpu'):
    """Where a receipt was measured: Python, CPU, packages and, with torch loaded, its live flags.

    torch is imported only for a device other than the CPU; on the CPU its flags are read only when
    something already imported it. Live flags, not
    policy constants."""
    name = _device_name(device)
    kind = _device_type(name)
    processor = _processor()
    packages = {}
    for package in ('numpy', 'torch', 'scipy'):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    out = {'python': platform.python_version(), 'implementation': platform.python_implementation(),
           'platform': platform.platform(), 'machine': platform.machine(), 'processor': processor,
           'logical_cpus': os.cpu_count(), 'packages': packages,
           'thread_env': {k: os.environ.get(k) for k in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                                                         'OPENBLAS_NUM_THREADS')}}
    torch = _module('torch')
    if torch is None and kind != 'cpu':
        try:
            import torch
        except ImportError:
            torch = None
    if torch is not None:
        out['torch'] = {
            'version': _attempt(lambda: str(torch.__version__)),
            'cuda': _attempt(lambda: torch.version.cuda),
            'cudnn': _attempt(lambda: torch.backends.cudnn.version()),
            'threads': _attempt(lambda: torch.get_num_threads()),
            'deterministic': _attempt(lambda: bool(torch.are_deterministic_algorithms_enabled())),
            'cudnn_benchmark': _attempt(lambda: bool(torch.backends.cudnn.benchmark)),
            'cudnn_deterministic': _attempt(lambda: bool(torch.backends.cudnn.deterministic)),
            'tf32_matmul': _attempt(lambda: bool(torch.backends.cuda.matmul.allow_tf32)),
            'tf32_cudnn': _attempt(lambda: bool(torch.backends.cudnn.allow_tf32)),
            'float32_matmul_precision': _attempt(lambda: torch.get_float32_matmul_precision()),
        }
    else:
        out['torch'] = None
    if kind == 'cuda' and torch is not None:
        def cuda_device():
            index = torch.device(name).index
            index = torch.cuda.current_device() if index is None else index
            prop = torch.cuda.get_device_properties(index)
            return {'type': 'cuda', 'index': index, 'name': prop.name, 'capability': [prop.major, prop.minor],
                    'total_memory': int(prop.total_memory), 'uuid': str(getattr(prop, 'uuid', None))}
        out['device'] = _attempt(cuda_device) or {'type': 'cuda', 'name': None}
    elif kind == 'mps':
        out['device'] = {'type': 'mps', 'name': processor, 'macos': platform.mac_ver()[0] or None}
    elif kind == 'cpu':
        out['device'] = {'type': 'cpu', 'name': processor}
    else:
        out['device'] = {'type': kind, 'name': None}
    return out


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _git(root, *args):
    out = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise subprocess.CalledProcessError(out.returncode, args, out.stdout, out.stderr)
    return out.stdout


def git_state(root=None, files=()):
    """The commit, whether the tree differs from it, and the SHA-256 of each named file.

    dirty: ``git status --porcelain`` over tracked files, or over just ``files`` when given, where
    an untracked named file also counts (it is not in the commit). Never raises when git or the
    repository is missing; commit and dirty are then None. A missing named file hashes to None."""
    root = pathlib.Path(root) if root is not None else ROOT
    files = [str(f) for f in files]
    out = {'commit': None, 'dirty': None, 'dirty_paths': [], 'files_sha256': {}}
    for f in files:
        path = pathlib.Path(f) if os.path.isabs(f) else root / f
        try:
            out['files_sha256'][f] = _sha256(path) if path.is_file() else None
        except OSError:
            out['files_sha256'][f] = None
    try:
        commit = _git(root, 'rev-parse', 'HEAD').strip()
        if len(commit) == 40 and all(c in '0123456789abcdef' for c in commit):
            out['commit'] = commit
            if files:
                status = _git(root, 'status', '--porcelain', '--untracked-files=all', '--', *files)
            else:
                status = _git(root, 'status', '--porcelain', '--untracked-files=no')
            lines = [line for line in status.splitlines() if line.strip()]
            out['dirty'] = bool(lines)
            out['dirty_paths'] = [line[3:] for line in lines][:_MAX_PATHS]
    except (OSError, subprocess.SubprocessError):
        out['commit'], out['dirty'], out['dirty_paths'] = None, None, []
    return out


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# The gate.

def _peak_reader(name):
    """(reset, read) for this CUDA device's peak allocated bytes, else None."""
    if _device_type(name) != 'cuda':
        return None
    import torch
    device = torch.device(name)
    return (lambda: torch.cuda.reset_peak_memory_stats(device),
            lambda: int(torch.cuda.max_memory_allocated(device)))


def _run_once(fn, args, kwargs, sync, peak):
    if peak is not None:
        peak[0]()
    out = fn(*args, **kwargs)
    sync()
    return out, (peak[1]() if peak is not None else None)


def benchmark(reference, candidate, *, args=(), kwargs=None, setup=None, device='cpu', warmup=DEFAULT_WARMUP,
              repeats=DEFAULT_REPEATS, number=1, atol=0.0, rtol=0.0, bitwise=False, equal_nan=False,
              check_dtype=True, control='perturb', name=None, dtype=None, sizes=None, source_files=(), root=None,
              clock=time.perf_counter, sync=None):
    """Gate, then time: the receipt of ``candidate`` against ``reference`` on the same inputs.

    In order: (a) validate; (b) run each arm once on its own inputs (setup() when given) and compare
    the outputs under the rule; (c) build the control (the reference output moved past the rule, or
    control(copy of it) when control is a callable; None skips it) and require that it fails the
    rule, else 'invalid-control'; (d) on a mismatch return 'refused-mismatch' without timing the
    candidate; (e) time both arms, warm-up calls alternating, then ``repeats`` samples per arm in
    ABBA order with a sync before every clock read; (f) compare the last outputs again, else
    'refused-unstable'; (g) 'pass' with speedup = reference min / candidate min, the ratio of the
    medians, and the median of the per-repeat ratios. On CUDA the peak allocated bytes of each arm's
    first call are recorded (they include memory allocated before the call)."""
    _check_counts(warmup, repeats, number)
    rule = _rule(atol, rtol, bitwise, equal_nan, check_dtype)
    if not (control is None or control == 'perturb' or callable(control)):
        raise ValueError("control must be 'perturb', a callable or None")
    if setup is not None and not callable(setup):
        raise ValueError('setup must be a zero-argument callable or None')
    if sizes is not None and (not isinstance(sizes, dict) or {'inputs', 'outputs'} & set(sizes)):
        raise ValueError("sizes must be a dict without the keys 'inputs' and 'outputs'")
    if dtype is not None and not isinstance(dtype, str):
        raise ValueError('dtype must be a string or None')
    device_name = _device_name(device)
    sync = _resolve_sync(device_name, sync)
    git = git_state(root, source_files)
    created = _now()
    peak = _peak_reader(device_name)

    ref_args, ref_kwargs = _inputs(setup, args, kwargs)
    described_inputs = _describe({'args': ref_args, 'kwargs': ref_kwargs})
    found_dtype = dtype if dtype is not None else _first_float_dtype([ref_args, ref_kwargs])
    ref_out, ref_peak = _run_once(reference, ref_args, ref_kwargs, sync, peak)
    del ref_args, ref_kwargs
    cand_args, cand_kwargs = _inputs(setup, args, kwargs)
    cand_out, cand_peak = _run_once(candidate, cand_args, cand_kwargs, sync, peak)
    del cand_args, cand_kwargs
    comparison = compare_outputs(ref_out, cand_out, **rule)

    if control is None:
        control_record = {'kind': None, 'comparison': None, 'failed_as_required': None}
    else:
        ctl_out = _perturb(ref_out, atol, rtol) if control == 'perturb' else control(_clone(ref_out))
        ctl_cmp = compare_outputs(ref_out, ctl_out, **rule)
        control_record = {'kind': 'perturb' if control == 'perturb' else 'caller', 'comparison': ctl_cmp,
                          'failed_as_required': not ctl_cmp['pass']}
        del ctl_out

    receipt = {'schema': SCHEMA, 'kind': KIND, 'name': name or f'{_qualname(reference)} vs {_qualname(candidate)}',
               'created_utc': created, 'status': None, 'reason': None,
               'speedup': None, 'speedup_median': None, 'speedup_paired_median': None,
               'device': device_name, 'dtype': found_dtype,
               'sizes': dict({'inputs': described_inputs,
                              'outputs': {'reference': _describe(ref_out), 'candidate': _describe(cand_out)}},
                             **(sizes or {})),
               'settings': {'warmup': warmup, 'repeats': repeats, 'number': number, 'order': 'ABBA',
                            'clock': _qualname(clock), 'sync': _sync_description(sync)},
               'comparison': comparison, 'control': control_record, 'post_check': None, 'timing': None,
               'peak_device_bytes': ({'reference': ref_peak, 'candidate': cand_peak} if peak is not None else None),
               'callables': {'reference': _qualname(reference), 'candidate': _qualname(candidate)},
               'environment': None, 'git': git}

    def finish(status, reason):
        receipt['status'], receipt['reason'] = status, reason
        receipt['environment'] = environment(device_name)
        return receipt

    if control_record['failed_as_required'] is False:
        also = '' if comparison['pass'] else '; the candidate also differed from the reference'
        return finish('invalid-control', 'the control output passed the rule, so the rule cannot tell outputs '
                                         f'apart; nothing was timed{also}')
    if not comparison['pass']:
        return finish('refused-mismatch', f"the candidate output differs from the reference in "
                                          f"{comparison['different_elements']} element(s) of "
                                          f"{comparison['different_leaves']} leaf or leaves; the candidate was "
                                          f"not timed")
    del ref_out, cand_out

    arms = {'reference': reference, 'candidate': candidate}
    for _ in range(warmup):
        for label in ('reference', 'candidate'):
            a, k = _inputs(setup, args, kwargs)
            arms[label](*a, **k)
            sync()
    seconds = {'reference': [], 'candidate': []}
    last = {}
    for i in range(repeats):
        for label in (('reference', 'candidate') if i % 2 == 0 else ('candidate', 'reference')):
            a, k = _inputs(setup, args, kwargs)
            last[label] = None                                  # free the previous output before the sample
            elapsed, last[label] = _sample(arms[label], a, k, number, clock, sync)
            seconds[label].append(elapsed)
    timing = {label: _summary(seconds[label], warmup, repeats, number, clock, sync) for label in arms}
    receipt['timing'] = timing
    post = compare_outputs(last['reference'], last['candidate'], **rule)
    receipt['post_check'] = post
    del last
    if not post['pass']:
        return finish('refused-unstable', 'the last timed outputs differ under the rule (a stateful or '
                                          'nondeterministic arm, or a drifting reference); no speedup is reported')
    ref_t, cand_t = timing['reference'], timing['candidate']
    receipt['speedup'] = _ratio(ref_t['min_s'], cand_t['min_s'])
    receipt['speedup_median'] = _ratio(ref_t['median_s'], cand_t['median_s'])
    receipt['speedup_paired_median'] = _paired(ref_t['seconds'], cand_t['seconds'])
    return finish('pass', None)


def _paired(reference_seconds, candidate_seconds):
    ratios = [_ratio(r, c) for r, c in zip(reference_seconds, candidate_seconds)]
    if not ratios or any(r is None for r in ratios):
        return None
    return float(statistics.median(ratios))


def timing_receipt(name, timings, *, device='cpu', dtype=None, sizes=None, source_files=(), root=None):
    """A receipt of time_callable results with status 'timing-only' and no speedup keys at all, so a
    speedup can only come from benchmark(). For tools whose variants differ by design."""
    if not isinstance(timings, dict) or not timings:
        raise ValueError('timings must be a non-empty dict {label: time_callable result}')
    for label, timing in timings.items():
        if not isinstance(timing, dict) or not isinstance(timing.get('seconds'), list):
            raise ValueError(f'timings[{label!r}] is not a time_callable result')
        if not isinstance(timing.get('repeats'), int) or timing['repeats'] < MIN_REPEATS:
            raise ValueError(f'timings[{label!r}] has fewer than {MIN_REPEATS} repeats')
    if sizes is not None and not isinstance(sizes, dict):
        raise ValueError('sizes must be a dict or None')
    device_name = _device_name(device)
    return {'schema': SCHEMA, 'kind': KIND, 'name': str(name), 'created_utc': _now(), 'status': 'timing-only',
            'reason': 'timing only: no output comparison, so no speedup', 'device': device_name, 'dtype': dtype,
            'sizes': dict(sizes or {}), 'timing': {str(k): v for k, v in timings.items()},
            'environment': environment(device_name), 'git': git_state(root, source_files)}


# Storage and re-checking.

def _jsonable(x):
    """Non-finite floats to None, tuples to lists, numpy scalars to Python, for strict JSON."""
    if isinstance(x, bool) or x is None or isinstance(x, (int, str)):
        return x
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if _is_npscalar(x):
        return _jsonable(x.item())
    raise TypeError(f'a receipt holds only JSON values; got {type(x).__name__}')


def write_receipt(receipt, path, *, overwrite=False):
    """Write the receipt as strict JSON (non-finite floats become None) through a temporary file,
    fsync and an atomic rename. Raises FileExistsError when ``path`` exists and overwrite is False."""
    path = pathlib.Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(str(path))
    text = json.dumps(_jsonable(receipt), indent=1, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)                   # mkstemp makes it 0600; a receipt is for reading
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)                              # no-clobber: fails if path appeared meanwhile
            except FileExistsError:
                raise
            except OSError:
                if path.exists():
                    raise FileExistsError(str(path)) from None
                os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def _close(value, expected):
    if value is None or expected is None:
        return value is None and expected is None
    return abs(value - expected) <= _RELATIVE * abs(expected)


def _check_timing(label, timing, problems):
    if not isinstance(timing, dict):
        problems.append(f'timing {label} is missing')
        return None
    seconds = timing.get('seconds')
    if not isinstance(seconds, list) or not seconds or not all(isinstance(s, (int, float)) for s in seconds):
        problems.append(f'timing {label} has no seconds')
        return None
    if not isinstance(timing.get('repeats'), int) or timing['repeats'] < MIN_REPEATS:
        problems.append(f'timing {label} has fewer than {MIN_REPEATS} repeats')
    elif len(seconds) != timing['repeats']:
        problems.append(f'timing {label} has {len(seconds)} samples for {timing["repeats"]} repeats')
    if timing.get('min_s') != min(seconds):
        problems.append(f'timing {label} min_s is not the minimum of its seconds')
    if timing.get('median_s') != statistics.median(seconds):
        problems.append(f'timing {label} median_s is not the median of its seconds')
    return seconds


def check_receipt(receipt):
    """Problems found in a receipt, empty when it is valid. Entries starting 'warning:' are not
    errors: no control, no git commit, or a tree that differs from its commit."""
    if not isinstance(receipt, dict):
        return ['receipt is not a mapping']
    problems = []
    if receipt.get('schema') != SCHEMA:
        problems.append(f"schema is {receipt.get('schema')!r}, expected {SCHEMA}")
    if receipt.get('kind') != KIND:
        problems.append(f"kind is {receipt.get('kind')!r}, expected {KIND!r}")
    status = receipt.get('status')
    if status not in STATUSES:
        problems.append(f'status {status!r} is not one of {STATUSES}')
        return problems
    if status == 'timing-only':
        present = [k for k in SPEEDUP_KEYS if k in receipt]
        if present:
            problems.append(f'a timing-only receipt carries {present}')
        timings = receipt.get('timing')
        if not isinstance(timings, dict) or not timings:
            problems.append('timing-only receipt has no timings')
        else:
            for label, timing in timings.items():
                _check_timing(label, timing, problems)
        return problems + _warnings(receipt, control=False)
    missing = [k for k in SPEEDUP_KEYS if k not in receipt]
    if missing:
        problems.append(f'missing {missing}')
    settings = receipt.get('settings') or {}
    if not isinstance(settings.get('repeats'), int) or settings['repeats'] < MIN_REPEATS:
        problems.append(f'settings.repeats is under {MIN_REPEATS}')
    comparison = receipt.get('comparison') or {}
    control = receipt.get('control') or {}
    post = receipt.get('post_check')
    timing = receipt.get('timing')
    if status != 'pass':
        carried = [k for k in SPEEDUP_KEYS if receipt.get(k) is not None]
        if carried:
            problems.append(f'status {status} carries {carried}')
    if status in ('refused-mismatch', 'invalid-control') and timing is not None:
        problems.append(f'status {status} carries timing')
    if status == 'refused-mismatch' and comparison.get('pass') is not False:
        problems.append('refused-mismatch without a failed comparison')
    if status == 'invalid-control' and control.get('failed_as_required') is not False:
        problems.append('invalid-control without a control that passed')
    if status == 'refused-unstable' and (not isinstance(post, dict) or post.get('pass') is not False):
        problems.append('refused-unstable without a failed post-check')
    if status == 'pass':
        if comparison.get('pass') is not True:
            problems.append('pass without a passing comparison')
        if not isinstance(post, dict) or post.get('pass') is not True:
            problems.append('pass without a passing post-check')
        if control.get('kind') is not None and control.get('failed_as_required') is not True:
            problems.append('pass without a control that failed as required')
        if not isinstance(timing, dict):
            problems.append('pass without timing')
        else:
            ref = _check_timing('reference', timing.get('reference'), problems)
            cand = _check_timing('candidate', timing.get('candidate'), problems)
            if ref and cand:
                expected = {'speedup': _ratio(min(ref), min(cand)),
                            'speedup_median': _ratio(statistics.median(ref), statistics.median(cand)),
                            'speedup_paired_median': _paired(ref, cand)}
                for key, value in expected.items():
                    if not _close(receipt.get(key), value):
                        problems.append(f'{key} {receipt.get(key)!r} does not match the timing ({value!r})')
    return problems + _warnings(receipt, control=True)


def _warnings(receipt, control):
    out = []
    if control and (receipt.get('control') or {}).get('kind') is None:
        out.append('warning: no control was run')
    git = receipt.get('git') or {}
    if git.get('commit') is None:
        out.append('warning: no git commit recorded')
    if git.get('dirty') is True:
        out.append('warning: the source tree differed from its commit')
    return out
