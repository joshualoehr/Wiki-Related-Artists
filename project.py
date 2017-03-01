import json
import re
import regex
from urllib.parse import urlencode
from urllib.request import urlopen


# Endpoints
WIKIDATA  = "https://wikidata.org/w/api.php?"
WIKIMEDIA = "https://wikimedia.org/api/rest_v1"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php?"

# Constants
DATE_START = "20000101" # 01 Jan 2000
DATE_END   = "20170228" # 28 Feb 2017


def api_get_json(endpoint, params, redirects=False):
    url = endpoint + urlencode(params).replace("%7C", "|")

    if redirects:
        url = url + "&redirects"

    print("GET %s (%s)" % (params.get('titles', params.get('ids')), url))

    res = urlopen(url)
    str = res.read().decode('utf-8')
    return json.loads(str)


def get_wikipedia_page(title, prop, **kwargs):
    params = {
        "format": "json",
        "action": "query",
        "prop": prop,
        "titles": title.replace(" ", "_"),
        "continue": ""
    }
    params.update(kwargs)

    res = api_get_json(WIKIPEDIA, params, redirects=True)
    page = res.get('query').get('pages').popitem()[1]  # selects first (and assumedly only) dict value from 'pages'
    if not page or page.get('missing') == "":
        print("No wikipedia page found for %s" % title)
        return None
    return page


def get_wikidata_page(page_id):
    params = {
        "format": "json",
        "action": "wbgetentities",
        "props": "claims",
        "ids": page_id,
        "continue": ""
    }

    res = api_get_json(WIKIDATA, params)
    page = res.get('entities').get(page_id)
    return page


def is_artist_page(link_title):
    # Retrieve wikibase_id for wikidata query
    wp_page = get_wikipedia_page(link_title, "pageprops", **{"ppprop": "wikibase_item"})
    if not wp_page:
        return False

    wikibase_id = wp_page.get("pageprops")
    wikibase_id = wikibase_id.get("wikibase_item")

    # Get wikidata entity
    wd_page = get_wikidata_page(wikibase_id)

    # Check that this entity has a 'discography' property
    discog_prop = "P358"
    is_artist = bool(wd_page.get("claims").get(discog_prop))

    return is_artist

def get_linked_artists(artist):
    # Fetch titles of all links on this artist's page
    wp_page = get_wikipedia_page(artist, "links|revisions", **{"pllimit": "100", "rvprop": "content"})

    def get_associated_acts(content):
        if 'associated_acts' not in content:
            return []

        associated_acts = []
        content = regex.search(r"(?<=associated_acts.+?{{\w+?\|).+?(?=}})", content, regex.S).group(0)
        content = [re.sub('\* |[\*\[\]\{\}]', '', line) for line in content.splitlines()]
        for title in content:
            title = title.replace("&nbsp;", " ")
            if "|" in title:
                title = title.split("|")[0]
            associated_acts.append(title.strip())

        return [s for s in associated_acts if s != '']

    associated_acts = get_associated_acts(wp_page.get('revisions')[0].get('*'))
    link_titles = [link.get('title') for link in wp_page.get('links')]

    return [title for title in list(set(link_titles[0:5]) | set(associated_acts)) if is_artist_page(title)]


def order_by_page_view(titles):
    for title in titles:
        endpoint = "https://wikimedia.org/api/rest_v1"
        query = "/metrics/pageviews/per-article/en.wikipedia.org/all-access/user/{0}/monthly/{1}/{2}".format(title, DATE_START, DATE_END)
    return titles


def compare_related(wiki_artists, spotify_artists):
    return (0, 0.0)


if __name__ == '__main__':
    # argparse

    input_names = ["Tame Impala"]

    for input_name in input_names:
        if not is_artist_page((input_name)):
            print("{0} is not a valid articile title, or has no listed discography (is this a musical artist?)".format(input_name))
            exit(1)

        print(get_linked_artists(input_name))

        # wiki_related_artists = order_by_page_view(get_linked_artists(input_name))
        # spotify_related_artists = []
        # accuracy = compare_related(wiki_related_artists, spotify_related_artists)
        #
        # print("Wiki-Related suggested {0} ({1:.2f}%) of Spotify's related artists".format(*accuracy))