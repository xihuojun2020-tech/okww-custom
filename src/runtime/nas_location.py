"""Owner's NAS aliases; custom hosts and shares are never rewritten."""
HOSTS = ('192.168.3.173',)
LEGACY_HOSTS = ('192.168.3.172', '192.168.3.161', '192.168.3.170')
SHARE = '羲火君 共享给我'
LEGACY_SHARE = 'xihuojun 共享给我'
DEFAULT_TARGET = rf'\\{HOSTS[0]}\{SHARE}\AI诊断'


def candidates(target):
    target = str(target)
    parts = target.replace('/', '\\').split('\\')
    if (len(parts) < 4 or parts[:2] != ['', ''] or
            parts[2] not in HOSTS + LEGACY_HOSTS or parts[3] not in (SHARE, LEGACY_SHARE, 'AI诊断')):
        return (target,)
    hosts = (parts[2], *(h for h in HOSTS if h != parts[2])) if parts[2] in HOSTS else HOSTS
    suffix = '\\'.join([SHARE, *parts[3:]]) if parts[3] == 'AI诊断' else '\\'.join([SHARE, *parts[4:]])
    return tuple('\\\\' + host + '\\' + suffix for host in hosts)


def credential_shares(share):
    parts = str(share).split('\\')
    if len(parts)!=4 or parts[2] not in HOSTS+LEGACY_HOSTS or parts[3] not in (SHARE,LEGACY_SHARE):
        return (share,)
    return tuple(dict.fromkeys([share, *('\\\\'+host+'\\'+name
        for host in HOSTS+LEGACY_HOSTS for name in (SHARE,LEGACY_SHARE))]))
