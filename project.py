import argparse
import json
import re
import regex
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


# Endpoints
SPOTIFY   = "https://api.spotify.com/v1/artists/%s/related-artists"
WIKIDATA  = "https://wikidata.org/w/api.php?"
WIKIMEDIA = "https://wikimedia.org/api/rest_v1"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php?"

# Constants
DATE_START = "20000101" # 01 Jan 2000
DATE_END   = "20170228" # 28 Feb 2017


def api_get_json(endpoint, params, req_desc, redirects=False):
    url = endpoint + urlencode(params).replace("%7C", "|")
    url = url + "&redirects" if redirects else url

    req_info = (req_desc, url)
    try:
        res = urlopen(url)
        charset = res.info().get_param('charset') or 'utf-8'
        print("GET 200 - %s (%s)" % req_info)
        obj = json.loads(res.read().decode(charset))
        if obj.get('query') and obj['query'].get('pages') and obj['query']['pages'].get('-1'):
            return None
        return obj
    except HTTPError as err:
        print("GET " + str(err.code) + " - %s (%s)" % req_info)
    except UnicodeEncodeError:
        print("GET ERR - unable to utf-8 encode %s" % url)


def get_wikipedia_page(title, prop, **kwargs):
    title = title.replace(" ", "_")
    params = {
        "format": "json",
        "action": "query",
        "prop": prop,
        "titles": title
    }
    params.update(kwargs)

    res = api_get_json(WIKIPEDIA, params, "Wikipedia %s" % title, redirects=True)
    if not res:
        return None

    # selects first (and assumedly only) dict value from 'pages'
    page = res.get('query').get('pages').popitem()[1]
    if page and not page.get('missing'):
        return page


def get_wikidata_page(page_id):
    params = {
        "format": "json",
        "action": "wbgetentities",
        "props": "claims",
        "ids": page_id,
        "continue": ""
    }

    res = api_get_json(WIKIDATA, params, "Wikidata %s" % page_id)
    if res:
        return res.get('entities').get(page_id)


def get_wikimedia_page_views(title):
    params = ("metrics", "pageviews", "per-article", "en.wikipedia.org",
        "all-access", "user", title, "monthly", DATE_START, DATE_END)
    endpoint = str(WIKIMEDIA + '/' + '/'.join(params))

    res = api_get_json(endpoint, {}, "Wikimedia %s" % title)
    if not res:
        return -1

    items = res.get('items')
    views = [i.get('views', 0) for i in items]
    return sum(views)


def get_spotify_related_artists(artist_id):
    if not artist_id:
        return []

    endpoint = SPOTIFY % artist_id
    res = api_get_json(endpoint, {}, "Spotify %s" % artist_id)
    if not res:
        return []

    artists = res.get('artists')
    return [artist.get('name', 'MISSING') for artist in artists]


def is_artist_page(link_title, get_spotify_id=False):
    no_result = (False, None) if get_spotify_id else False
    # Retrieve wikibase_id for wikidata query
    wp_page = get_wikipedia_page(link_title, "pageprops", **{"ppprop": "wikibase_item"})
    if not wp_page:
        return no_result

    wikibase_id = wp_page.get("pageprops")
    wikibase_id = wikibase_id.get("wikibase_item")

    # Get wikidata entity
    wd_page = get_wikidata_page(wikibase_id)
    if not wd_page:
        return no_result

    # Check that this entity has any properties indicating it is a musical artist
    claims = wd_page.get("claims")
    artist_props = ("P358", "P1728", "P1902")
    spotify_prop = "P1902"
    # artist_props = ("P358", "P1953", "P434", "P1728", "P1902")
    is_artist = any([claims.get(prop, False) for prop in artist_props])
    spotify_id = claims.get(spotify_prop, None)
    if spotify_id:
        spotify_id = spotify_id[0].get('mainsnak').get('datavalue').get('value')

    return is_artist if not get_spotify_id else (is_artist, spotify_id)


def get_linked_artists(artist):
    # Fetch titles of all links on this artist's page
    wp_page = get_wikipedia_page(artist, "links|revisions", **{"pllimit": "100", "rvprop": "content"})

    def get_associated_acts(content):
        if 'associated_acts' not in content:
            return []

        try:
            associated_acts = []
            content = regex.search(r"(?<=associated_acts.+?{{\w+?\|).+?(?=}})", content, regex.S).group(0)
            content = [re.sub('\* |[\*\[\]\{\}]', '', line) for line in content.splitlines()]
            for title in content:
                title = title.replace("&nbsp;", " ")
                if "|" in title:
                    title = title.split("|")[0]
                associated_acts.append(title.strip())

            return [s for s in associated_acts if s != '']
        except AttributeError:
            print("Regex could not find associated_acts titles")
            return []

    link_titles = [link.get('title') for link in wp_page.get('links')]
    link_titles.extend(get_associated_acts(wp_page.get('revisions')[0].get('*')))

    return [title for title in link_titles if is_artist_page(title)]


def order_by_page_view(titles):
    titles = list(set(titles))
    page_views = [(title, get_wikimedia_page_views(title)) for title in titles]
    page_views.sort(key=lambda x: x[1], reverse=True)
    return page_views


def compare_related(wiki_artists, spotify_artists):
    wiki_artists = [s.lower() for s in wiki_artists]
    spotify_artists = [s.lower() for s in spotify_artists]

    # Get the length of the intersection of both lists
    num_same = len(set(wiki_artists) & set(spotify_artists))
    percent = 100 * num_same / len(spotify_artists)
    return num_same, percent


if __name__ == '__main__':
    parser = argparse.ArgumentParser('Suggests (questionably) related artists by leveraging the power of Wikipedia.')
    parser.add_argument('--artist', type=str, required=False,
        help='The artist to obtain suggestions for')
    parser.add_argument('--artists_file', type=str, required=False,
        help='Optional input file with artist names on each line')
    args = parser.parse_args()

    input_names = set()
    if args.artist:
        input_names |= {args.artist}
    if args.artists_file:
        with open(args.artists_file) as artist_file:
            input_names |= set([line.strip() for line in artist_file.readlines()])

    results = {}
    for input_name in input_names:
        is_artist, spotify_id = is_artist_page(input_name, get_spotify_id=True)
        if not is_artist:
            print("{0} is not a valid article title, or has no listed discography (is this a musical artist?)".format(input_name))
        else:
            results.update({input_name: (order_by_page_view(get_linked_artists(input_name)), spotify_id)})

    for input_name, (suggestions, spotify_id) in results.items():
        wiki_artists = [name for (name, views) in suggestions if views > -1]
        print("If you like %s, you should try: %s" % (input_name, ', '.join(wiki_artists)))

        spotify_artists = get_spotify_related_artists(spotify_id)
        if spotify_artists:
            accuracy = compare_related(wiki_artists, spotify_artists)
            print("Wiki-Related Artists suggested %d (%.2f%%) of Spotify's related artists for %s" % (*accuracy, input_name))
        else:
            print("Unfortunately, %s is not on Spotify, so these suggestions are as good as it gets." % input_name)