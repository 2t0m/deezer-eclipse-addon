"""Run live, non-blocking endpoint diagnostics before Gunicorn starts."""

import logging
import os
from urllib.parse import urlencode

from app import API_KEY, app, login_success

logger = logging.getLogger('startup')


class StartupReport:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def ok(self, label, detail=''):
        self.passed += 1
        suffix = f' - {detail}' if detail else ''
        logger.info(f'OK   {label}{suffix}')

    def fail(self, label, detail):
        self.failed += 1
        logger.error(f'FAIL {label} - {detail}')

    def skip(self, label, detail):
        self.skipped += 1
        logger.warning(f'WARN {label} - {detail}')

    def summary(self):
        message = (
            f'Summary: {self.passed} OK, {self.failed} failed, '
            f'{self.skipped} skipped'
        )
        if self.failed:
            logger.error(message)
        elif self.skipped:
            logger.warning(message)
        else:
            logger.info(message)


def call_endpoint(
    client,
    report,
    label,
    path,
    method='GET',
    expected_status=(200,),
    headers=None,
    buffered=False,
    validator=None
):
    try:
        response = client.open(
            path,
            method=method,
            headers=headers or {},
            buffered=buffered
        )
    except Exception as error:
        report.fail(label, f'{type(error).__name__}: {error}')
        return None

    if response.status_code not in expected_status:
        body = response.get_data(as_text=True)[:200].replace('\n', ' ')
        report.fail(label, f'HTTP {response.status_code}: {body}')
        return None

    try:
        if validator:
            validator(response)
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        report.fail(label, str(error))
        return None

    report.ok(label, f'HTTP {response.status_code}')
    return response


def require_json_keys(*keys):
    def validate(response):
        payload = response.get_json(silent=True)
        if not isinstance(payload, dict):
            raise AssertionError('response is not a JSON object')
        missing = [key for key in keys if key not in payload]
        if missing:
            raise AssertionError(f'missing JSON fields: {", ".join(missing)}')

    return validate


def require_items(response):
    payload = response.get_json(silent=True) or {}
    if not payload.get('items'):
        raise AssertionError('catalog returned no items')


def require_audio(response):
    if not response.content_type.startswith('audio/mpeg'):
        raise AssertionError(f'unexpected content type: {response.content_type}')
    if not response.get_data():
        raise AssertionError('audio response is empty')


def run():
    report = StartupReport()
    query = os.environ.get('STARTUP_CHECK_QUERY', 'Daft Punk').strip() or 'Daft Punk'
    token = API_KEY or 'startup-check'
    base_path = f'/{token}'
    client = app.test_client()

    logger.info('Running live Deezer diagnostics')
    if login_success:
        report.ok('Deezer ARL login')
    else:
        report.fail('Deezer ARL login', 'login failed or DEEZER_ARL is missing')

    manifest_response = call_endpoint(
        client,
        report,
        'manifest',
        f'{base_path}/manifest.json',
        validator=require_json_keys('id', 'resources', 'types')
    )
    if manifest_response:
        manifest = manifest_response.get_json()
        expected_resources = {'search', 'stream', 'isrc', 'resolve', 'catalog'}
        missing_resources = expected_resources.difference(manifest.get('resources', []))
        if missing_resources:
            report.fail('manifest capabilities', f'missing: {sorted(missing_resources)}')
        else:
            report.ok('manifest capabilities')

    search_query = urlencode({'q': query})
    search_response = call_endpoint(
        client,
        report,
        'search',
        f'{base_path}/search?{search_query}',
        validator=require_json_keys('tracks', 'albums', 'artists', 'playlists')
    )
    alias_response = call_endpoint(
        client,
        report,
        'music search alias',
        f'{base_path}/music/search?{search_query}',
        validator=require_json_keys('tracks', 'albums', 'artists', 'playlists')
    )

    search_data = merge_search_results(search_response, alias_response)
    tracks = search_data.get('tracks') or []
    albums = search_data.get('albums') or []
    artists = search_data.get('artists') or []
    playlists = search_data.get('playlists') or []
    track = tracks[0] if tracks else None

    if track:
        check_track_endpoints(client, report, base_path, track)
    else:
        for label in (
            'stream resolver query', 'stream resolver path', 'resolve metadata',
            'resolve ISRC', 'Apple Music warm', 'Apple Music stream',
            'audio proxy OPTIONS', 'audio proxy HEAD', 'audio proxy Range'
        ):
            report.skip(label, 'search returned no streamable track')

    check_detail_endpoint(client, report, base_path, 'album', albums, ('id', 'title', 'tracks'))
    check_detail_endpoint(client, report, base_path, 'artist', artists, ('id', 'name', 'topTracks', 'albums'))
    check_detail_endpoint(client, report, base_path, 'playlist', playlists, ('id', 'title', 'tracks'))

    for catalog_id in ('charts', 'popular-albums', 'featured-playlists'):
        call_endpoint(
            client,
            report,
            f'catalog {catalog_id}',
            f'{base_path}/catalog/{catalog_id}?skip=0',
            validator=require_items
        )

    if API_KEY:
        call_endpoint(
            client,
            report,
            'authentication rejection',
            '/wrong-token/manifest.json',
            expected_status=(401,)
        )
    else:
        report.skip('authentication rejection', 'API_KEY is not configured')
    report.summary()


def merge_search_results(*responses):
    """Merge successful search responses by resource ID for dependent checks."""
    merged = {key: [] for key in ('tracks', 'albums', 'artists', 'playlists')}
    seen = {key: set() for key in merged}

    for response in responses:
        payload = response.get_json() if response else {}
        for key in merged:
            for item in payload.get(key) or []:
                item_id = str(item.get('id', ''))
                if item_id and item_id not in seen[key]:
                    seen[key].add(item_id)
                    merged[key].append(item)

    return merged


def check_track_endpoints(client, report, base_path, track):
    track_id = track['id']
    title = track.get('title', '')
    artist_name = track.get('artist', '')
    duration_ms = int(track.get('duration', 0)) * 1000
    isrc = track.get('isrc', '')

    call_endpoint(client, report, 'stream resolver query', f'{base_path}/stream?trackId={track_id}')
    call_endpoint(
        client,
        report,
        'stream resolver path',
        f'{base_path}/stream/{track_id}',
        validator=require_json_keys('url')
    )
    call_endpoint(client, report, 'stream OPTIONS', f'{base_path}/stream', method='OPTIONS')
    call_endpoint(client, report, 'stream path OPTIONS', f'{base_path}/stream/{track_id}', method='OPTIONS')

    resolve_query = urlencode({
        'title': title,
        'artist': artist_name,
        'durationMs': duration_ms
    })
    call_endpoint(
        client,
        report,
        'resolve metadata',
        f'{base_path}/resolve?{resolve_query}',
        validator=require_json_keys('item')
    )

    if isrc:
        encoded_isrc = urlencode({'isrc': isrc})
        call_endpoint(
            client,
            report,
            'resolve ISRC',
            f'{base_path}/resolve-isrc?{encoded_isrc}',
            validator=require_json_keys('trackId')
        )
        call_endpoint(client, report, 'Apple Music warm', f'{base_path}/applemusic/warm?{encoded_isrc}')
        call_endpoint(
            client,
            report,
            'Apple Music stream',
            f'{base_path}/applemusic/stream?{encoded_isrc}',
            validator=require_json_keys('url')
        )
    else:
        report.skip('resolve ISRC', 'search result has no ISRC')
        report.skip('Apple Music warm', 'search result has no ISRC')
        report.skip('Apple Music stream', 'search result has no ISRC')

    call_endpoint(client, report, 'audio proxy OPTIONS', f'{base_path}/proxy/stream/{track_id}', method='OPTIONS')
    call_endpoint(client, report, 'audio proxy HEAD', f'{base_path}/proxy/stream/{track_id}', method='HEAD')
    range_response = call_endpoint(
        client,
        report,
        'audio proxy Range',
        f'{base_path}/proxy/stream/{track_id}',
        expected_status=(206,),
        headers={'Range': 'bytes=0-2047'},
        buffered=True,
        validator=require_audio
    )
    if range_response and not range_response.headers.get('Content-Range'):
        report.fail('audio proxy Content-Range', 'header is missing')
    elif range_response:
        report.ok('audio proxy Content-Range', range_response.headers['Content-Range'])


def check_detail_endpoint(client, report, base_path, resource, results, required_keys):
    label = f'{resource} details'
    if not results:
        report.skip(label, f'search returned no {resource}')
        return

    call_endpoint(
        client,
        report,
        label,
        f'{base_path}/{resource}/{results[0]["id"]}',
        validator=require_json_keys(*required_keys)
    )


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        logger.error(
            f'FAIL unexpected diagnostic error: {type(error).__name__}: {error}'
        )