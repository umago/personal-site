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
import math
import os
import sys

import jinja2
import markdown

POSTS_PER_PAGE = 10


def get_markdown_files():
    md_list = []
    for root, dirs, files in os.walk('.'):
        md_list += [os.path.join(root, f) for f in files if f.endswith('.md')]
    return md_list


def _sanitize_metadata(meta):
    for key, value in meta.items():

        if isinstance(value, list):
            value = value[0]

        if key == 'date':
            value = datetime.datetime.strptime(value, "%d-%m-%Y")

        meta[key] = value
    return meta


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
        is_post = src.startswith('./posts/')
        dst_file = os.path.splitext(src)[0] + '.html'

        with open(src, 'r') as f:
            html = md.convert(f.read())

        extra_args = {}
        if is_post:
            meta = _sanitize_metadata(md.Meta)
            extra_args['__post_title__'] = meta['title']
            extra_args['__post_date__'] = meta['date']
            extra_args['__post_headline__'] = meta['headline']
            meta['__href__'] = '/' + os.path.join(
                'posts', os.path.basename(dst_file))
            posts.append(meta)

        with open(dst_file, 'w') as f:
            f.write(template.render(**template_args, **extra_args, __content__=html,))

    posts = sorted(posts, key=lambda k: k['date'], reverse=True)
    total_pages = max(1, math.ceil(len(posts) / POSTS_PER_PAGE))

    for page_num in range(1, total_pages + 1):
        start = (page_num - 1) * POSTS_PER_PAGE
        page_posts = posts[start:start + POSTS_PER_PAGE]

        if page_num == 1:
            out_path = 'index.html'
        else:
            page_dir = os.path.join('page', str(page_num))
            os.makedirs(page_dir, exist_ok=True)
            out_path = os.path.join(page_dir, 'index.html')

        pagination = {
            '__current_page__': page_num,
            '__total_pages__': total_pages,
            '__has_prev__': page_num > 1,
            '__has_next__': page_num < total_pages,
            '__prev_url__': '/index.html' if page_num == 2 else f'/page/{page_num - 1}/',
            '__next_url__': f'/page/{page_num + 1}/',
        }

        with open(out_path, 'w') as f:
            f.write(template.render(**template_args, **pagination, __posts__=page_posts))


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
