# Copyright (c) 2016 Lucas Alvares Gomes <lucasagomes@gmail.com>

# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom
# the Software is furnished to do so, subject to the following
# conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
# KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE
# AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import datetime
import json
import os
import sys

import jinja2
import markdown


def get_markdown_files():
    md_list = []
    for root, dirs, files in os.walk('.'):
        md_list += [os.path.join(root, f) for f in files if f.endswith('.md')]
    return md_list


def _sanitize_posts_metadata(posts):
    for p in posts:
        for key, value in p.items():

            if isinstance(value, list):
                value = value[0]

            if key == 'date':
                value = datetime.datetime.strptime(value, "%d-%m-%Y")

            p[key] = value

    return sorted(posts, key=lambda k: k['date'], reverse=True)


def build_html(template, template_args):
    md_list = get_markdown_files()
    posts = []
    for src in md_list:
        md = markdown.Markdown(output_format='html5',
                               extensions=['markdown.extensions.meta',
                                           'markdown.extensions.footnotes',
                                           'markdown.extensions.fenced_code',
                                           'markdown.extensions.tables',
                                           'markdown.extensions.toc',
                                           'markdown.extensions.abbr'])
        with open(src, 'r') as f:
            html = md.convert(f.read())

        dst_file = os.path.basename(src)
        dst_file = os.path.splitext(src)[0] + '.html'

        with open(dst_file, 'w') as f:
            f.write(template.render(**template_args, __content__=html))

        if src.startswith('./posts/'):
            meta = md.Meta
            meta['__href__'] = os.path.join(
                'posts', os.path.basename(dst_file))
            posts.append(meta)

    posts = _sanitize_posts_metadata(posts)
    with open('index.html', 'w') as f:
        f.write(template.render(**template_args, __posts__=posts))


def main():
    with open('config.json', 'r') as f:
        conf = json.load(f)

    env = jinja2.Environment(loader=jinja2.FileSystemLoader('.'))
    template = env.get_template('index.html.template')
    template_args = {
        '__links__': conf.get('links', []),
        'title': conf.get('title'),
        'header': conf.get('header'),
        'footer': conf.get('footer'),
    }
    build_html(template, template_args)


if __name__ == "__main__":
    sys.exit(main())
