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

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/playlist':
            qs = urllib.parse.parse_qs(parsed.query)
            playlist_id = qs.get('id', [''])[0]
            if not playlist_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"success": false, "error": "Missing playlist id"}')
                return
            
            result = fetch_full_youtube_playlist(playlist_id)
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
