#!/usr/bin/env python3
"""Track pinned native sources without downloading/executing upstream code."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {
    'RTL_WMBUS_REF': 'xaelsouth/rtl-wmbus',
    'WMBUSMETERS_REF': 'wmbusmeters/wmbusmeters',
}


class GitHub:
    def __init__(self, token):
        self.token = token
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):
                return None
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, method='GET', data=None):
        headers = {'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'diehl2mqtt-dependency-monitor'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        payload = None if data is None else json.dumps(data).encode()
        request = urllib.request.Request('https://api.github.com/' + path,
                                         headers=headers, method=method, data=payload)
        with self.opener.open(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('GitHub response exceeds its size limit')
        return json.loads(raw) if raw else None


def pinned_refs(dockerfile):
    refs = {}
    for name in DEPENDENCIES:
        matches = re.findall(r'^ARG ' + name + r'=([0-9a-f]{40})$', dockerfile, re.M)
        if len(matches) != 2 or len(set(matches)) != 1:
            raise ValueError('Expected identical immutable build/runtime pins for ' + name)
        refs[name] = matches[0]
    return refs


def inspect(api, variable, pinned, now=None):
    repo = DEPENDENCIES[variable]
    base = 'repos/' + repo
    info = api.request(base)
    head = api.request(base + '/commits/' + urllib.parse.quote(info['default_branch'], safe=''))
    candidate = head['sha']
    if not re.fullmatch('[0-9a-f]{40}', candidate):
        raise ValueError('Invalid upstream revision')
    date = head['commit']['committer']['date']
    stale = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(date.replace('Z', '+00:00')) > timedelta(days=365)
    archived = info.get('archived', False)
    if pinned == candidate and not archived and not stale:
        return None
    url = 'https://github.com/' + repo
    compare = url + '/compare/' + pinned + '...' + candidate
    lines = [f'<!-- diehl2mqtt-native:{variable} -->',
             f'The pinned **{repo}** source needs review.', '',
             f'- Current pin: [`{pinned[:12]}`]({url}/commit/{pinned})',
             f'- Default-branch revision: [`{candidate[:12]}`]({url}/commit/{candidate})',
             f'- Latest commit date: {date}', f'- [Compare changes]({compare})']
    if archived:
        lines.append('- **The upstream repository is archived.** Review continued maintenance or alternatives.')
    if stale:
        lines.append('- **No default-branch commit in over a year.** Review upstream maintenance status.')
    lines += ['', 'This monitor tracks default-branch commits, not only tagged releases. '
              'A newer commit is a review candidate, not an automatic recommendation to upgrade.', '',
              f'For an accepted update, change both `{variable}` pins in `Dockerfile`. '
              'Review upstream interfaces and licenses, then run the full build, synthetic decryption, '
              'MQTT/TLS and deployment checks. Verify live reception before releasing. '
              'The monitor never changes pins, merges code or deploys an update.']
    return '\n'.join(lines) + '\n'


def sync_issue(api, repo, variable, body, issues):
    marker = f'<!-- diehl2mqtt-native:{variable} -->'
    matches = [issue for issue in issues if not issue.get('pull_request') and marker in (issue.get('body') or '')]
    # Reuse the most recent monitor issue; never modify unrelated issues.
    existing = max(matches, key=lambda issue: issue['number'], default=None)
    if body is None:
        if existing and existing['state'] == 'open':
            api.request(f'repos/{repo}/issues/{existing["number"]}', 'PATCH', {'state': 'closed'})
        return
    title = 'Dependency review: ' + DEPENDENCIES[variable].split('/')[1]
    if existing:
        # Respect a dismissed candidate. A different revision/status reopens it.
        if existing.get('body') != body:
            api.request(f'repos/{repo}/issues/{existing["number"]}', 'PATCH',
                        {'title': title, 'body': body, 'state': 'open'})
    else:
        api.request(f'repos/{repo}/issues', 'POST', {'title': title, 'body': body})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-issues', action='store_true', help='Maintain bot-owned GitHub review issues')
    args = parser.parse_args()
    api = GitHub(os.environ.get('GH_TOKEN', ''))
    refs = pinned_refs((ROOT / 'Dockerfile').read_text())
    # Complete all upstream checks before making any issue changes. API failures
    # fail the workflow rather than being mistaken for an up-to-date dependency.
    reports = {variable: inspect(api, variable, pinned) for variable, pinned in refs.items()}
    for variable, body in reports.items():
        print(body or f'{variable}: matches active upstream default branch')
    if args.write_issues:
        repo = os.environ['GITHUB_REPOSITORY']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Invalid target repository')
        issues = []
        page = 1
        while True:
            query = urllib.parse.urlencode({'state': 'all', 'creator': 'github-actions[bot]', 'per_page': 100, 'page': page})
            batch = api.request(f'repos/{repo}/issues?{query}')
            issues.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        for variable, body in reports.items():
            sync_issue(api, repo, variable, body, issues)


if __name__ == '__main__':
    main()
