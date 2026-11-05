"""Portable publication document and image package exports."""
import json
import zipfile


def write_exports(directory, content, names):
    markdown = '# ' + content['title'] + '\n\n' + content['summary'] + '\n\n' + content['body']
    markdown += '\n\n' + ' '.join('#' + tag for tag in content['tags'])
    markdown += '\n\n## 配图\n\n' + '\n\n'.join(f'![{card["heading"]}]({name})' for name, card in zip(names, content['cards']))
    markdown += '\n\n## 配乐建议（尚未匹配平台音乐）\n\n' + content['music']['reason'] + '\n' + ' / '.join(content['music']['keywords'])
    markdown += '\n\n## 来源与理解范围\n\n' + str(content['source_url']) + '\n\n' + '\n'.join(str(x) for x in content['limitations'])
    markdown += '\n\n## 配图来源\n\n' + '\n\n'.join(f'{trace["attribution"]}\n{trace["page_url"]}\n{trace["license"]}：{trace["license_url"]}' for trace in content['image_traces'] if trace.get('attribution'))
    (directory / 'content.md').write_text(markdown, encoding='utf-8')
    (directory / 'content.json').write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(directory / 'package.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        generated_files = [path.name for path in directory.iterdir() if path.name.startswith('illustration-') and path.suffix in {'.png', '.json'}]
        extra = ['preflight.json'] if (directory / 'preflight.json').is_file() else []
        for name in [*names, *generated_files, *extra, 'cover.png', 'source.json', 'content.md', 'content.json']:
            archive.write(directory / name, name)
