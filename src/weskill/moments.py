"""Decode native SNS XML and aggregate one native page at a time."""
import json
import xml.etree.ElementTree as ET


def decode_moment(row, include_xml=False):
    row = dict(row)
    xml = row.pop('native_xml', '')
    if include_xml:
        row['native_xml'] = xml
    if not xml:
        return row
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        row['xml_error'] = str(error)
        return row
    def tree(element):
        children = list(element)
        if not children:
            return {**element.attrib, 'text': element.text or ''} if element.attrib else element.text or ''
        result = dict(element.attrib)
        for child in children:
            value = tree(child)
            if child.tag in result:
                old = result[child.tag]
                result[child.tag] = old + [value] if isinstance(old, list) else [old, value]
            else:
                result[child.tag] = value
        return result
    row['details'] = tree(root)
    return row


def read_moments(run, limit, cursor, contact_id, include_xml):
    if cursor is not None:
        value = json.loads(cursor)
        if not isinstance(value, dict) or value.get('contact_id') != contact_id:
            raise ValueError('Cursor belongs to another timeline')
        ident = value.get('max_id')
        if not isinstance(ident, str) or not ident.isascii() or not ident.isdecimal() or not 0 <= int(ident) < 2**64:
            raise ValueError('Invalid moments cursor')
    rows, top, seen, seen_top, pages = [], [], set(), set(), 0
    seen_cursors = {cursor}
    while True:
        page = run('moments_read', {'limit': limit - len(rows) if limit else 0,
                                   'cursor': cursor, 'contact_id': contact_id})
        pages += 1
        result = page.get('result') or {}
        if page['status'] != 'client_success':
            if rows:
                page['partial_result'] = {'moments': rows, 'top_moments': top,
                                           'next_cursor': cursor, 'pages_fetched': pages - 1}
            return page
        for row in result.get('moments', []):
            if row['moment_id'] not in seen:
                seen.add(row['moment_id'])
                rows.append(decode_moment(row, include_xml))
        for row in result.get('top_moments', []):
            if row['moment_id'] not in seen_top:
                seen_top.add(row['moment_id'])
                top.append(decode_moment(row, include_xml))
        following = result.get('next_cursor')
        stalled = result.get('has_more') and (not following or following in seen_cursors or
            not result.get('moments') and not result.get('continuation_only'))
        result.update(moments=rows, top_moments=top, returned=len(rows), pages_fetched=pages,
                      pagination_stalled=bool(stalled or result.get('pagination_stalled')))
        if not result.get('has_more') or limit and len(rows) >= limit or result['pagination_stalled']:
            return page
        seen_cursors.add(following)
        cursor = following


def prepare_images(image_paths, directory, token, expected):
    """Copy selected bytes and produce upload JPEGs with separate thumbnails."""
    import hashlib
    import os
    from pathlib import Path
    from PIL import Image, ImageOps
    from .media import _stage
    directory = Path(directory) / 'moments-media' / hashlib.sha256(token.encode()).hexdigest()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = []
    for index, (source, identity) in enumerate(zip(image_paths, expected, strict=True)):
        source = Path(source)
        original = _stage(source, directory / (str(index) + '-source'), identity['sha256'], token, False)
        data, thumb = directory / (str(index) + '.jpg'), directory / (str(index) + '-thumb.jpg')
        with Image.open(original) as opened:
            image = ImageOps.exif_transpose(opened).convert('RGBA')
            rgb = Image.new('RGB', image.size, 'white')
            rgb.paste(image, mask=image.getchannel('A'))
            # Retain source dimensions. The small separate preview is an upload
            # artifact; there is no toolkit cap on source dimensions or count.
            for target, thumbnail in ((data, False), (thumb, True)):
                converted = rgb.copy()
                if thumbnail:
                    converted.thumbnail((256, 256))
                temporary = target.with_name(target.name + '.tmp')
                converted.save(temporary, format='JPEG', quality=90)
                os.chmod(temporary, 0o600)
                temporary.replace(target)
            width, height = rgb.size
        result.append({'source_path': str(original), 'data_path': str(data), 'thumb_path': str(thumb),
                       'width': width, 'height': height,
                       'client_id': hashlib.md5((token + ':' + str(index)).encode()).hexdigest()})
    return result
