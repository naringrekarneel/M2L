import http.server
import socketserver
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
import os

PORT = 8000
DIRECTORY = r"C:\M2P"

def fetch_full_youtube_playlist(playlist_id):
    """
    Fetches ALL videos from ANY public YouTube playlist (even 80+, 100+, 200+ videos)
    using YouTube's InnerTube API with automatic pagination and RSS fallback.
    """
    browse_id = f'VL{playlist_id}' if not playlist_id.startswith('VL') else playlist_id
    url = 'https://www.youtube.com/youtubei/v1/browse?prettyPrint=false'
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }

    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240101.01.00",
                "hl": "en",
                "gl": "US"
            }
        },
        "browseId": browse_id
    }

    videos = []
    playlist_title = ''
    author = ''
    continuation_token = None

    def extract_continuation_token(it):
        # 1. Modern lockup continuationItemViewModel (YouTube 2024+)
        if 'continuationItemViewModel' in it:
            civm = it['continuationItemViewModel']
            cmd = civm.get('continuationCommand', {})
            tok = (
                cmd.get('innertubeCommand', {}).get('continuationCommand', {}).get('token')
                or cmd.get('continuationCommand', {}).get('token')
                or cmd.get('token')
            )
            if tok:
                return tok

        # 2. Classic continuationItemRenderer
        if 'continuationItemRenderer' in it:
            cir = it['continuationItemRenderer']
            tok = (
                cir.get('continuationEndpoint', {}).get('continuationCommand', {}).get('token')
                or cir.get('continuationCommand', {}).get('token')
            )
            if tok:
                return tok

        # 3. Deep search for token in any continuation container
        for k, v in it.items():
            if 'continuation' in k.lower():
                stack = [v]
                while stack:
                    curr = stack.pop()
                    if isinstance(curr, dict):
                        if 'token' in curr and isinstance(curr['token'], str):
                            return curr['token']
                        stack.extend(curr.values())
                    elif isinstance(curr, list):
                        stack.extend(curr)
        return None

    def parse_items(items):
        nonlocal continuation_token
        for it in items:
            # Check for continuation tokens
            tok = extract_continuation_token(it)
            if tok:
                continuation_token = tok

            # 1. Modern lockupViewModel (YouTube 2024+)
            if 'lockupViewModel' in it:
                lvm = it['lockupViewModel']
                vid = lvm.get('contentId')
                meta = lvm.get('metadata', {}).get('lockupMetadataViewModel', {})
                title = meta.get('title', {}).get('content')
                
                # Extract duration badge
                dur = None
                overlays = lvm.get('contentImage', {}).get('thumbnailViewModel', {}).get('overlays', [])
                for ov in overlays:
                    badges = ov.get('thumbnailBottomOverlayViewModel', {}).get('badges', [])
                    for b in badges:
                        t = b.get('thumbnailBadgeViewModel', {}).get('text')
                        if t and (':' in t):
                            dur = t
                            break
                    if dur:
                        break

                if vid and title:
                    item_data = {
                        'id': vid,
                        'title': title
                    }
                    if dur:
                        item_data['durationText'] = dur
                    videos.append(item_data)
            # 2. playlistVideoRenderer (Classic YouTube)
            elif 'playlistVideoRenderer' in it:
                pvr = it['playlistVideoRenderer']
                vid = pvr.get('videoId')
                title = pvr.get('title', {}).get('runs', [{}])[0].get('text')
                dur = pvr.get('lengthText', {}).get('simpleText')
                if vid and title:
                    item_data = {
                        'id': vid,
                        'title': title
                    }
                    if dur:
                        item_data['durationText'] = dur
                    videos.append(item_data)

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode('utf-8'))

        # Extract Title
        playlist_title = res.get('metadata', {}).get('playlistMetadataRenderer', {}).get('title', '')
        if not playlist_title:
            header = res.get('header', {}).get('playlistHeaderRenderer', {})
            playlist_title = header.get('title', {}).get('simpleText', '')
        if not playlist_title:
            playlist_title = 'YouTube Playlist'

        # Extract Author
        try:
            author = res.get('header', {}).get('playlistHeaderRenderer', {}).get('ownerText', {}).get('runs', [{}])[0].get('text', '')
        except Exception:
            pass

        # Parse initial page items
        tabs = res.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
        if tabs:
            tab0 = tabs[0].get('tabRenderer', {}).get('content', {})
            sectionList = tab0.get('sectionListRenderer', {}).get('contents', [])
            for sec in sectionList:
                itemSection = sec.get('itemSectionRenderer', {}).get('contents', [])
                parse_items(itemSection)
                if 'playlistVideoListRenderer' in sec:
                    parse_items(sec['playlistVideoListRenderer'].get('contents', []))

        # Check engagement panels for continuation token if not found in tabs
        if not continuation_token:
            for panel in res.get('panels', []):
                for sec in panel.get('engagementPanelSectionListRenderer', {}).get('content', {}).get('sectionListRenderer', {}).get('contents', []):
                    for item in sec.get('itemSectionRenderer', {}).get('contents', []):
                        tok = extract_continuation_token(item)
                        if tok:
                            continuation_token = tok
                            break

        # Paginate to fetch remaining batches (e.g. videos 100-200, 200-300...)
        page_count = 1
        while continuation_token and len(videos) < 600 and page_count < 15:
            page_count += 1
            cont_payload = {
                "context": payload["context"],
                "continuation": continuation_token
            }
            continuation_token = None
            cont_req = urllib.request.Request(url, data=json.dumps(cont_payload).encode('utf-8'), headers=headers)
            try:
                with urllib.request.urlopen(cont_req, timeout=10) as c_resp:
                    c_res = json.loads(c_resp.read().decode('utf-8'))
                actions = c_res.get('onResponseReceivedActions', [])
                for act in actions:
                    items = act.get('appendContinuationItemsAction', {}).get('continuationItems', [])
                    parse_items(items)
            except Exception as e:
                print(f"Pagination page {page_count} error:", e)
                break

    except Exception as e:
        print("InnerTube primary fetch failed, falling back to RSS:", e)

    # Fallback to RSS if InnerTube returned no videos
    if not videos:
        rss_url = f'https://www.youtube.com/feeds/videos.xml?playlist_id={playlist_id}'
        try:
            r_req = urllib.request.Request(rss_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(r_req, timeout=8) as resp:
                xml_data = resp.read().decode('utf-8')
            root = ET.fromstring(xml_data)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015',
                'media': 'http://search.yahoo.com/mrss/'
            }
            if not playlist_title or playlist_title == 'YouTube Playlist':
                feed_title = root.find('atom:title', ns)
                if feed_title is not None and feed_title.text:
                    playlist_title = feed_title.text
            if not author:
                auth_el = root.find('atom:author/atom:name', ns)
                if auth_el is not None and auth_el.text:
                    author = auth_el.text

            entries = root.findall('atom:entry', ns)
            for entry in entries:
                v_title = entry.find('atom:title', ns).text
                v_id = entry.find('yt:videoId', ns).text
                videos.append({
                    'id': v_id,
                    'title': v_title
                })
        except Exception as e:
            print("RSS fallback also failed:", e)

    return {
        'success': len(videos) > 0,
        'title': playlist_title,
        'author': author,
        'videoCount': len(videos),
        'videos': videos
    }

def fetch_single_youtube_video(video_id):
    """
    Fetches a single 10-12 hour 'One-Shot' full course video, extracting:
    1. Video details (title, channel, total length) via /player
    2. Structured chapters via /next playerBar & macroMarkers
    3. Fallback timestamp chapters from description text
    4. Fallback automatic time-chunk segmentation (e.g. 30-45m modules)
    """
    player_url = 'https://www.youtube.com/youtubei/v1/player?prettyPrint=false'
    next_url = 'https://www.youtube.com/youtubei/v1/next?prettyPrint=false'
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240101.01.00",
                "hl": "en",
                "gl": "US"
            }
        },
        "videoId": video_id
    }

    video_title = 'YouTube Mega Course'
    author = ''
    length_seconds = 0
    raw_desc = ''

    # 1. Fetch Player Details
    try:
        req = urllib.request.Request(player_url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            p_data = json.loads(resp.read().decode('utf-8'))
        details = p_data.get('videoDetails', {})
        video_title = details.get('title', video_title)
        author = details.get('author', author)
        length_seconds = int(details.get('lengthSeconds', 0))
        raw_desc = details.get('shortDescription', '')
    except Exception as e:
        print("Player details fetch error:", e)

    raw_chapters = []

    # 2. Try fetching structured chapters via Next API
    try:
        n_req = urllib.request.Request(next_url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        with urllib.request.urlopen(n_req, timeout=10) as resp:
            n_data = json.loads(resp.read().decode('utf-8'))
        
        # Look in playerOverlays
        markers_map = (
            n_data.get('playerOverlays', {})
                  .get('playerOverlayRenderer', {})
                  .get('decoratedPlayerBarRenderer', {})
                  .get('decoratedPlayerBarRenderer', {})
                  .get('playerBar', {})
                  .get('multiMarkersPlayerBarRenderer', {})
                  .get('markersMap', [])
        )
        for m in markers_map:
            val = m.get('value', {})
            if 'chapters' in val:
                for ch in val['chapters']:
                    cr = ch.get('chapterRenderer', {})
                    t = cr.get('title', {}).get('simpleText') or cr.get('title', {}).get('runs', [{}])[0].get('text')
                    start_ms = int(cr.get('timeRangeStartMillis', 0))
                    if t:
                        raw_chapters.append({
                            'title': t.strip(),
                            'startSec': start_ms // 1000
                        })
                if raw_chapters:
                    break

        # Look in engagementPanels (macroMarkersListItemRenderer)
        if not raw_chapters:
            for panel in n_data.get('engagementPanels', []):
                items = (
                    panel.get('engagementPanelSectionListRenderer', {})
                         .get('content', {})
                         .get('structuredDescriptionContentRenderer', {})
                         .get('items', [])
                )
                for it in items:
                    cards = it.get('horizontalCardListRenderer', {}).get('cards', [])
                    for card in cards:
                        mr = card.get('macroMarkersListItemRenderer', {})
                        t = mr.get('title', {}).get('simpleText') or mr.get('title', {}).get('runs', [{}])[0].get('text')
                        start_ms = int(mr.get('timeRangeStartMillis', 0))
                        if t:
                            raw_chapters.append({
                                'title': t.strip(),
                                'startSec': start_ms // 1000
                            })
    except Exception as e:
        print("Next structured chapters fetch error:", e)

    # 3. Fallback: Parse timestamps from video description
    if not raw_chapters and raw_desc:
        import re
        lines = re.findall(r'(?:^|\n)\s*[\(\[]?(\d{1,2}:\d{2}(?::\d{2})?)[\)\]]?\s*[\-–—:]?\s*(.+?)(?=\n|$)', raw_desc)
        for ts_str, name in lines:
            parts = ts_str.split(':')
            if len(parts) == 2:
                s = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                s = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                continue
            cleaned_name = name.strip()
            if len(cleaned_name) > 2:
                raw_chapters.append({
                    'title': cleaned_name,
                    'startSec': s
                })

    # Sort raw_chapters by startSec and remove duplicates
    raw_chapters = sorted(raw_chapters, key=lambda x: x['startSec'])
    seen_sec = set()
    unique_chapters = []
    for c in raw_chapters:
        if c['startSec'] not in seen_sec:
            seen_sec.add(c['startSec'])
            unique_chapters.append(c)

    # 4. If still no chapters, segment the 10-12 hour video into smart 30-45m modules
    if not unique_chapters:
        import math
        total_s = length_seconds if length_seconds > 0 else 36000 # default 10h if unknown
        chunk_sec = 2100 # ~35 mins per segment
        seg_count = max(4, math.ceil(total_s / chunk_sec))
        for i in range(seg_count):
            s = i * chunk_sec
            if s >= total_s:
                break
            h_s = s // 3600
            m_s = (s % 3600) // 60
            ts_label = f"{h_s}:{m_s:02d}:00" if h_s > 0 else f"{m_s:02d}:00"
            unique_chapters.append({
                'title': f"Module {i+1}: Deep-Dive Session (at {ts_label})",
                'startSec': s
            })

    # Build final video lessons with durationSec, durationText, and direct timestamp URL
    final_lessons = []
    total_len = length_seconds if length_seconds > 0 else (unique_chapters[-1]['startSec'] + 1800)

    for i, ch in enumerate(unique_chapters):
        start_s = ch['startSec']
        next_s = unique_chapters[i + 1]['startSec'] if i + 1 < len(unique_chapters) else total_len
        dur_s = max(60, next_s - start_s)
        
        m = dur_s // 60
        s = dur_s % 60
        h = m // 60
        m = m % 60
        dur_text = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

        start_h = start_s // 3600
        start_m = (start_s % 3600) // 60
        start_sec = start_s % 60
        start_ts = f"{start_h}:{start_m:02d}:{start_sec:02d}" if start_h > 0 else f"{start_m}:{start_sec:02d}"

        final_lessons.append({
            'id': f"oneshot_{video_id}_s{start_s}",
            'title': ch['title'],
            'durationSec': dur_s,
            'durationText': dur_text,
            'timestamp': start_ts,
            'startSec': start_s,
            'ytUrl': f"https://www.youtube.com/watch?v={video_id}&t={start_s}s",
            'isOneShot': True
        })

    tot_h = length_seconds // 3600
    tot_m = (length_seconds % 3600) // 60
    tot_dur_text = f"{tot_h}h {tot_m}m" if tot_h > 0 else f"{tot_m}m"

    return {
        'success': len(final_lessons) > 0,
        'isOneShot': True,
        'videoId': video_id,
        'title': video_title,
        'author': author,
        'totalDurationSec': length_seconds,
        'totalDurationText': tot_dur_text,
        'videoCount': len(final_lessons),
        'videos': final_lessons
    }

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/playlist':
            qs = urllib.parse.parse_qs(parsed.query)
            item_id = qs.get('id', [''])[0]
            if not item_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"success": false, "error": "Missing id"}')
                return
            
            # If item_id is a 11-char video ID, route to single video fetcher
            if len(item_id) == 11 and not item_id.startswith('PL') and not item_id.startswith('UU') and not item_id.startswith('FL'):
                result = fetch_single_youtube_video(item_id)
            else:
                result = fetch_full_youtube_playlist(item_id)

            payload = json.dumps(result).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        elif parsed.path == '/api/video':
            qs = urllib.parse.parse_qs(parsed.query)
            video_id = qs.get('id', [''])[0]
            if not video_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"success": false, "error": "Missing video id"}')
                return
            
            result = fetch_single_youtube_video(video_id)
            payload = json.dumps(result).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        return super().do_GET()

if __name__ == '__main__':
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"Serving at http://localhost:{PORT}")
        httpd.serve_forever()
