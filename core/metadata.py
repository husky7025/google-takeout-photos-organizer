import os
import re
import json
from datetime import datetime, timezone

# Common image/video extensions
MEDIA_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.heic', '.dng', '.gif', '.bmp', '.tiff', '.webp',
    '.mov', '.mp4', '.m4v', '.avi', '.mkv', '.wmv', '.3gp'
}

def detect_extension_by_magic(filepath: str) -> str | None:
    """Detect actual file extension from binary header (magic bytes)."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(32)
        if len(header) < 4:
            return None
        
        # JPEG: FF D8 FF
        if header.startswith(b'\xff\xd8\xff'):
            return '.jpg'
        # PNG: 89 50 4E 47 0D 0A 1A 0A
        if header.startswith(b'\x89PNG\r\n\x1a\n'):
            return '.png'
        # GIF: GIF87a or GIF89a
        if header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
            return '.gif'
        # TIFF / DNG: II*\x00 (little endian) or MM\x00* (big endian)
        if header.startswith(b'II*\x00') or header.startswith(b'MM\x00*'):
            return '.dng'
        
        # ISO Base Media File Format (MP4, MOV, HEIC)
        # Bytes 4-8 are 'ftyp'
        if len(header) >= 12 and header[4:8] == b'ftyp':
            brand = header[8:12].decode('latin1', errors='ignore').strip()
            if brand in ['heic', 'mif1', 'msf1', 'heix', 'hevc']:
                return '.heic'
            elif brand in ['qt  ', 'moov']:
                return '.mov'
            elif brand in ['mp41', 'mp42', 'isom', 'iso2', 'avc1']:
                return '.mp4'
            else:
                return '.mp4'
    except Exception:
        pass
    return None


def parse_metadata_json(json_path: str) -> dict:
    """Parse Google Photos JSON metadata file and extract essential properties."""
    meta = {
        'title': None,
        'description': '',
        'timestamp': None,
        'latitude': None,
        'longitude': None,
        'altitude': None
    }
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        meta['title'] = data.get('title')
        meta['description'] = data.get('description', '')

        # Timestamp priority: photoTakenTime > creationTime
        time_info = data.get('photoTakenTime') or data.get('creationTime')
        if time_info and 'timestamp' in time_info:
            ts = int(time_info['timestamp'])
            if ts > 0:
                meta['timestamp'] = ts
        
        # Geo data
        geo = data.get('geoData')
        if geo:
            lat = float(geo.get('latitude', 0.0))
            lon = float(geo.get('longitude', 0.0))
            alt = float(geo.get('altitude', 0.0))
            if lat != 0.0 or lon != 0.0:
                meta['latitude'] = lat
                meta['longitude'] = lon
                meta['altitude'] = alt
    except Exception as e:
        meta['error'] = str(e)
    return meta
