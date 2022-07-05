# This file contains helper functions for plotting maps.
import pandas as pd
import numpy as np

import folium
import branca.element as bre
from scipy.spatial import ConvexHull

import data_wrangling
from clustering import add_loc_clusters
import emission.storage.decorations.trip_queries as esdtq

DENVER_COORD = [39.7392, -104.9903]
MTV_COORD = [37.3861, -122.0839]

# list of valid default colors in folium
COLORS = [
    'darkred',
    'orange',
    'gray',
    'green',
    'darkblue',
    # 'lightblue',  # too hard to see on map
    'purple',
    # 'pink', # too hard to see on map
    'darkgreen',
    'lightgreen',
    # 'darkpurple', # this color does not exist?
    'cadetblue',
    # 'lightgray', # too hard to see point on map
    'black',
    'blue',
    # 'red', # reserved for noise/unlabeled data
    # 'lightred', # this color does not exist in folium?
    # 'beige', # too hard to see point on map
]


def plot_clusters(user_df,
                  alg,
                  loc_type,
                  radii=[50, 100, 150, 200],
                  cluster_unlabeled=False,
                  plot_unlabeled=False,
                  optics_min_samples=None,
                  optics_xi=0.05,
                  optics_cluster_method='xi',
                  map_loc=MTV_COORD):
    """ Plot points and clusters on a folium map. 
            
        Points with the same purpose will have the same color (unless there are more purposes than available colors in folium, in which case some colors may be duplicated). Hovering over a point will also reveal the purpose in the tooltip. 
        
        The clusters are visualized as convex hulls; their color doesn't mean anything for now, it's simply so we can distinguish between distinct clusters (which will be helpful when clusters overlap). 
    
        Args: 
            user_df (dataframe): must contain the following columns: 
                'start_loc', 'end_loc', 'user_input'
            alg (str): the clustering algorithm to be used. must be one of the 
                following: 'DBSCAN', 'oursim', 'OPTICS', 'SVM', 'fuzzy'
            loc_type (str): 'start' or 'end', the type of points to cluster
                TODO: allow for trip-wise clustering? 
            radii (int list): list of radii to pass to the clustering alg
            cluster_unlabeled (bool): whether or not unlabeled points are used 
                to generate clusters.
            plot_unlabeled (bool): whether or not to plot unlabeled points. If 
                True, they will be plotted as red points. 
            optics_min_samples (int): number of min samples if using the OPTICS 
                algorithm.
            optics_xi (float): xi value if using the xi method of the OPTICS algorithm.
            optics_cluster_method (str): method to use for the OPTICS 
                algorithm. either 'xi' or 'dbscan'
            map_loc (array-like): lat and lon coordinate for the default folium 
                map position. 
    
    """
    # TODO: refactor to take in kwargs so we can remove the mess of optics_*
    # variables that I was using when manually tuning that algorithm
    assert loc_type == 'start' or loc_type == 'end'
    assert 'start_loc' in user_df.columns
    assert 'end_loc' in user_df.columns
    assert 'user_input' in user_df.columns
    alg_options = ['DBSCAN', 'oursim', 'OPTICS', 'SVM', 'fuzzy']
    assert alg in alg_options

    fig = bre.Figure(figsize=(20, 20))
    fig_index = 0

    # clean up the dataframe by dropping entries with NaN locations and
    # reset index (because oursim needs the position of each trip to match
    # its nominal index)
    all_trips_df = user_df.dropna(subset=['start_loc', 'end_loc']).reset_index(
        drop=True)

    # expand the 'start_loc' and 'end_loc' column into 'start_lat',
    # 'start_lon', 'end_lat', and 'end_lon' columns
    all_trips_df = data_wrangling.expand_coords(all_trips_df)

    labeled_trips_df = all_trips_df.loc[all_trips_df.user_input != {}].dropna(
        subset=['purpose_confirm'])
    df_for_cluster = all_trips_df if cluster_unlabeled else labeled_trips_df

    df_for_cluster = add_loc_clusters(
        df_for_cluster,
        radii=radii,
        alg=alg,
        loc_type=loc_type,
        min_samples=2,
        optics_min_samples=optics_min_samples,
        optics_xi=optics_xi,
        optics_cluster_method=optics_cluster_method)

    for r in radii:
        fig_index = fig_index + 1
        m = folium.Map(location=map_loc, zoom_start=12)

        cluster_ids = df_for_cluster[
            f"{loc_type}_{alg}_clusters_{r}_m"].unique()

        # draw the convex hull of the clusters
        for i in range(len(cluster_ids)):
            c = cluster_ids[i]
            if c == -1:
                print(
                    'we should never get here because we want to convert the -1 cluster into single-trip clusters'
                )
                continue

            points_in_cluster = df_for_cluster[
                df_for_cluster[f"{loc_type}_{alg}_clusters_{r}_m"] == c]

            if np.isnan(c):
                raise Exception(
                    'nan cluster detected; all trips should have a proper cluster index'
                )

            m = plot_cluster_border(points_in_cluster,
                                    loc_type=loc_type,
                                    m=m,
                                    color=COLORS[i % (len(COLORS) - 1)])

        # plot all the destinations, color-coordinated by purpose
        # we want to plot these on *top* of the cluster circles so that we can
        # hover over the points and see the purpose on the tooltip
        m = plot_user_trips(user_df,
                            loc_type,
                            plot_100=False,
                            plot_unlabeled=plot_unlabeled,
                            m=m)

        # add plot to the figure
        fig.add_subplot(len(radii) / 2 + len(radii) % 2, 2,
                        fig_index).add_child(m)

    return fig


def plot_user_trips(user_df,
                    loc_type,
                    plot_100=True,
                    plot_500=False,
                    plot_unlabeled=False,
                    m=None):
    """ Args:
            user_df (dataframe): must contain the columns 'start/end_lat/lon'
            loc_type (str): 'start' or 'end'
            plot_100 (bool): whether or not to plot 100m radius circles around 
                each location point
            plot_500 (bool): whether or not to plot 500m radius circles around 
                each location point
            plot_500 (bool): whether or not to plot unlabeled points (if so, 
                they will be red)
            m (folium.Map): optional, an existing map onto which this function 
                will plot markers
    """
    assert loc_type == 'start' or loc_type == 'end'

    if m is None:
        m = folium.Map(location=MTV_COORD, zoom_start=13)

    purpose_list = user_df.purpose_confirm.dropna().unique()

    # plot circles with a 500m radius around each point
    if plot_500:
        for i, purpose in enumerate(purpose_list):
            if i < len(COLORS):
                color = COLORS[i]
            else:
                color = COLORS[len(COLORS) - 1]
            purpose_trips = user_df[user_df.purpose_confirm == purpose]
            for j in range(len(purpose_trips)):
                coords = purpose_trips[loc_type +
                                       '_loc'].iloc[j]['coordinates']
                folium.Circle([coords[1], coords[0]],
                              radius=500,
                              color=color,
                              opacity=0.2,
                              fill=True,
                              fill_opacity=0.1,
                              weight=1).add_to(m)
        if plot_unlabeled:
            unlabeled_trips = user_df[user_df.purpose_confirm.isna()]
            for j in range(len(unlabeled_trips)):
                coords = unlabeled_trips[loc_type +
                                         '_loc'].iloc[j]['coordinates']
                folium.Circle([coords[1], coords[0]],
                              radius=500,
                              color='red',
                              opacity=0.2,
                              fill=True,
                              fill_opacity=0.1,
                              weight=1).add_to(m)


# plot circles with a 100m radius around each point
    if plot_100:
        for i, purpose in enumerate(purpose_list):
            if i < len(COLORS):
                color = COLORS[i]
            else:
                color = COLORS[len(COLORS) - 1]
            purpose_trips = user_df[user_df.purpose_confirm == purpose]
            for j in range(len(purpose_trips)):
                coords = purpose_trips[loc_type +
                                       '_loc'].iloc[j]['coordinates']
                folium.Circle([coords[1], coords[0]],
                              radius=100,
                              color=color,
                              opacity=0.2,
                              fill=True,
                              fill_opacity=0.1,
                              weight=1).add_to(m)
        if plot_unlabeled:
            unlabeled_trips = user_df[user_df.purpose_confirm.isna()]
            for j in range(len(unlabeled_trips)):
                coords = unlabeled_trips[loc_type +
                                         '_loc'].iloc[j]['coordinates']
                folium.Circle([coords[1], coords[0]],
                              radius=100,
                              color='red',
                              opacity=0.2,
                              fill=True,
                              fill_opacity=0.1,
                              weight=1).add_to(m)

    # plot small circle marker on the very top so it doesn't get obscured by
    # the layers of 100m/500m circles
    for i, purpose in enumerate(purpose_list):
        if i < len(COLORS):
            color = COLORS[i]
        else:
            color = COLORS[len(COLORS) - 1]
        # print('{:<15} {:<15}'.format(color, purpose))
        purpose_trips = user_df[user_df.purpose_confirm == purpose]
        for j in range(len(purpose_trips)):
            coords = purpose_trips[loc_type + '_loc'].iloc[j]['coordinates']
            folium.CircleMarker([coords[1], coords[0]],
                                radius=2.5,
                                color=color,
                                tooltip=purpose).add_to(m)
    if plot_unlabeled:
        unlabeled_trips = user_df[user_df.purpose_confirm.isna()]
        for j in range(len(unlabeled_trips)):
            coords = unlabeled_trips[loc_type + '_loc'].iloc[j]['coordinates']
            folium.CircleMarker([coords[1], coords[0]],
                                radius=2.5,
                                color='red',
                                tooltip='UNLABELED').add_to(m)

    return m


def plot_cluster_border(points_df, loc_type, m=None, color='green'):
    """ plots a convex hull around the given points. 
    
        Args:
            points_df: dataframe with columns 'xxx_lat' and 'xxx_lon'
            loc_type (str): 'start' or 'end', the type of points to cluster
            m (folium.Map): optional, an existing map onto which this function 
                will plot markers
            color (str): cluster color. must be valid in folium. 
    """
    assert loc_type == 'start' or loc_type == 'end'
    if m is None:
        m = folium.Map(location=MTV_COORD, zoom_start=12)

    lats = points_df[loc_type + '_lat'].tolist()
    lons = points_df[loc_type + '_lon'].tolist()
    points = np.array([lats, lons]).T

    if len(points) > 2:
        hull = ConvexHull(points)
        border_points = points[hull.vertices]
    else:
        border_points = points

    folium.Polygon(
        border_points,  # list of points (latitude, longitude)
        color=color,
        weight=20,
        opacity=0.6,
        fill=True,
        fill_opacity=0.5).add_to(m)

    return m