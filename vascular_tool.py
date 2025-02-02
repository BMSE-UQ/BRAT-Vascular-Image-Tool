# TODO clean up whatever tf is going on with my imports, this is getting excessive
import matplotlib.pyplot as plt
from skimage import io
from skimage.color import rgb2gray, label2rgb
from skimage.morphology import (
    skeletonize,
    remove_small_objects,
    remove_small_holes,
    isotropic_dilation,
    isotropic_erosion,
)
from skimage.measure import label
from skimage.filters import gaussian, threshold_local, threshold_otsu
from skimage.exposure import equalize_adapthist, rescale_intensity
from skimage.draw import disk
from skimage.util import img_as_ubyte
import numpy as np
from scipy.ndimage import distance_transform_edt
import pandas as pd
from pathlib import Path
import argparse
import sknw
import os
from multiprocessing import Pool, cpu_count, set_start_method
import yaml
import networkx as nx
from time import time
from copy import deepcopy


nodeResults = []


def find_images_in_path(pathdir):
    path = Path(pathdir)
    images = list(path.glob("*.tif"))
    print(f"{len(images)} images found in directory")
    images.sort()
    return images


# def get_global_threshold(images):
#     #preallocate zeros for all the bins
#     histoTotal = np.zeros(255)
#     binVals = np.linspace(0,255,num=256)
#     for i,imageLoc in enumerate(images):
#         if i % 10 == 0:
#             img = skimage.io.imread(imageLoc)
#             imgGrey = img[:,:,1] #Take the green channel
#             imgAdapted1 = rescale_intensity(imgGrey)
#             imgAdapted = (skimage.exposure.equalize_adapthist(imgAdapted1,nbins=256)*255).astype(np.uint8)

#             #get the values in bin form
#             imgArray = imgAdapted.ravel()
#             imageHistoN, _ = np.histogram(imgArray, bins=binVals)
#             histoTotal = histoTotal + imageHistoN
#     #Use k-means clustering to determine the global threshold
#     # yen_thresh = threshold_yen(histoTotal)
#     return None


def get_running_approval():
    pass


def import_and_blur_image(imgPath, config):
    sigma = float(config.get("Blur Sigma"))
    img = io.imread(imgPath)

    #Get grey image depending on the config
    greyMethod = config["bw mode"]
    greyNumericalSup = config["bw val"]
    if greyMethod == "Average":
        if len(np.shape(img)) != 3:
            raise ValueError("RGB Image not provided")
        shape = np.shape(img)
        imgGrey = np.zeros((shape[0], shape[1]))
        for i in range(3):
            imgGrey += img[:, :, i]
        imgGrey = np.uint8( 1/3 * (imgGrey))
    elif greyMethod == "Human Eye Level":
        if len(np.shape(img)) != 3:
            raise ValueError("RGB Image not provided")
        imgGrey = rgb2gray(img)
    elif greyMethod == "Individual Channel":
        imgGrey = img[:, :, int(greyNumericalSup)]  # Take the green channel
    elif greyMethod == "BW Input":
        #check shape
        if len(np.shape(img)) != 2:
            raise ValueError("BW Image not provided")
        imgGrey = img
    
    rescaled_grey = rescale_intensity(imgGrey) 
    adapted_hist = equalize_adapthist(rescaled_grey)
    blurred = gaussian(
        adapted_hist, sigma=(sigma, sigma), truncate=3.5, channel_axis=-1
    )
    return img, blurred


def segment_image(blurred, config):
    # Convert to uint8
    uint8Image = (blurred * 255).astype(np.uint8)
    mode = config.get("segmentation mode")
    val = int(config.get("segmentatation val"))

    #Select what to do based upon mode variable
    if mode == "Global Threshold":
        thresh = val
    elif mode == "Otsu Global Adaptive":
        thresh = threshold_otsu(uint8Image)
    elif mode == "Otsu Local Adaptive":
        thresh = threshold_local(uint8Image, block_size=val)

    # Apply segmentation threshold
    segmentation = uint8Image > thresh
    return segmentation


def remove_holes_and_small_items(segmentation, config):
    min_object_size = int(config.get("Min Object Size"))
    min_hole_size = int(config.get("Min Hole Size"))
    ensmallend = remove_small_objects(
        segmentation, min_size=min_object_size, connectivity=8
    )
    dilated = isotropic_dilation(ensmallend, 1)
    unholed = remove_small_holes(dilated, area_threshold=min_hole_size)
    return unholed


def vessel_width_and_prune(skel, segmentation, config: dict):
    # Compute Distance Image using SCIPI
    distance_img = distance_transform_edt(segmentation)
    # Use skel as a mask to get distance_skel:
    distance_skel = distance_img * (skel > 0)
    # Prune skeleton if below required width
    new_skel = 2 * distance_skel > int(config.get("Minimum Vessel Width"))
    skel_width = new_skel * distance_img * 2
    return np.uint8(new_skel * 255), skel_width


def prune_skeleton_spurs_with_graph(
    graph: nx.MultiGraph, config: dict
) -> nx.MultiGraph:
    line_min = int(config.get("Min Spur Line Length"))
    nodeRemovalCandidates = []

    # If node removal is 0 simply return the graph unchanged
    if line_min <= 0:
        return graph

    # Continue as normal
    edges = graph.edges
    for edgeLoc in edges:
        edge = edges[edgeLoc]
        if np.size(edge.get("pts")) < line_min:
            # Check if nodes are on the edge
            for node in edgeLoc:
                neighbours = sum(1 for n in graph.neighbors(node) if n in graph.nodes())
                if neighbours == 1:
                    nodeRemovalCandidates.append(node)

    # Remove edges from the graph
    graph.remove_nodes_from(nodeRemovalCandidates)
    return graph


def construct_removal_dict(graph: nx.MultiGraph, edge: dict, oldNodes: tuple):
    outputDict = {}
    # Split the current edge in half
    length = edge["pts"].shape[0]  # Length of Array
    outputDict["NewNode"] = edge["pts"][length // 2]
    # Calculate Weight and Split List of Points in half (Node should be included in both)
    outputDict["weightAdj"] = edge["weight"] / 2
    outputDict["pointsArrays"] = np.split(edge["pts"], [length // 2], axis=0)
    # Get edge details for both nodes
    nodeEdges = []
    gen = (node for node in oldNodes if node != 0)
    for node in gen:
        nodes = nx.all_neighbors(graph, node)
        nodeEdges.append(nodes)
    # Fill out rest of dictionary
    outputDict["nodeEdges"] = nodeEdges
    outputDict["oldNodes"] = oldNodes

    return outputDict


def reconstruct_network_with_modifications(
    oldGraph: nx.MultiGraph, modifications: list[dict]
):
    # Copy old graph

    newGraph = deepcopy(oldGraph)
    nodeId = max(oldGraph.nodes) + 1
    for mod in modifications:
        # Remove Nodes
        oldNode = mod["oldNodes"]
        newGraph.remove_nodes_from(oldNode)
        # Add new Node in centre
        newPts = mod["NewNode"]
        newGraph.add_node(nodeId, pts=newPts, o=newPts)
        # Add edges for new Node (based upon old ones)
        # For Loop (LHS/RHS point)
        for i in range(2):
            connectedNodes = mod["nodeEdges"][i]
            for node in connectedNodes:
                if node in oldNode:
                    # Skip nodes we killed
                    continue
                oldEdge = oldGraph.edges[(oldNode[i], node, 0)]
                # Create new weights and points
                newWeight = oldEdge["weight"] + mod["weightAdj"]
                newPoints = np.append(oldEdge["pts"], mod["pointsArrays"][i], axis=0)
                # Create new edge
                newGraph.add_edge(nodeId, node, pts=newPoints, weight=newWeight)
        nodeId += 1
    # Clean up
    # This is proof that we need to recheck after each run
    # Can't be bothered
    oldGraph = deepcopy(newGraph)
    for node in oldGraph.nodes:
        if oldGraph.nodes[node] == {}:
            newGraph.remove_node(node)

    return newGraph


def flood_find(G: nx.MultiGraph, node: int, minLength: int):
    global nodeResults
    # depth-first search the graph to find all connected nodes
    returnNodes = []
    returnEdges = []
    if G.nodes[node]["touch"]:
        return returnNodes, returnEdges

    # Add current node to global list
    G.nodes[node]["touch"] = True

    # get connected nodes of node
    edges = [
        e
        for e in G.edges(node, keys=True)
        if np.size(G.edges[e].get("pts")) < minLength
    ]
    for edge in edges:
        # Extract other node from edge
        # Potential for many downstram nodes
        downStreamNodes = [
            n for i, n in enumerate(edge) if n != node and i != 2
        ]  # Node not equal to this one and not any sort of overlap
        # Nodes and Edges already added
        for n in downStreamNodes:
            if G.nodes[n]["touch"]:
                continue  # Already added elsewhere
            else:
                # Don't consider node if it is an end point
                if len(G.edges(n)) == 1:
                    continue
                # Add this edge
                returnEdges.append(edge)
                returnNodes.append(n)
                # Check what's downstream
                lowerNodes, lowerEdges = flood_find(G, n, minLength)
                returnEdges += lowerEdges
                returnNodes += lowerNodes

    if len(returnNodes) == 0 and len(returnEdges) > 0:
        raise (ValueError("Incorrect edges and nodes"))
    return returnNodes, returnEdges  # NEED TO SEPERATE THESE
# def flood_find(G: nx.MultiGraph, node: int, minLength: int, propogation: int):
#     returnNodes = []
#     returnEdges = []
#     if  G.nodes[node]["touch"]:
#         return returnNodes, returnEdges
    
#     if propogation > 1:
#         return returnNodes, returnEdges
    
#     #Now propogate along
#     # Add current node to global list
#     G.nodes[node]["touch"] = True

#     # get connected nodes of node
#     edges = [
#         e
#         for e in G.edges(node, keys=True)
#         if np.size(G.edges[e].get("pts")) < minLength
#     ]
#     print(edges)
#     #Get connected nodes, and their
#     # for edge in edges:
#     return [], []
        


def find_mean_node_position(G: nx.MultiGraph, nodes: list):
    xSum = 0
    ySum = 0
    for n in nodes:
        x, y = G.nodes[n]["o"]
        xSum += x
        ySum += y
    x = xSum / len(nodes)
    y = ySum / len(nodes)

    return x, y


def find_closest_edge_to_position(
    G: nx.multigraph, meanPos: tuple, edges: list, nodes: list
) -> tuple:
    # takes position, list of edges and a graph and finds the edge whos midpoint is closest

    # Error Handling Checks
    if len(edges) == 0:
        raise ValueError("No edges given for find closest edge")
    if len(meanPos) != 2:
        raise ValueError("Incorrect Dimension for 2D position")

    # Actual Computation
    closest = None
    closestDist = np.inf  # Any distance is closer than infty
    xMean, yMean = meanPos
    for e in edges:
        # Get mean position of the nodes
        # Assume straight line (slightly bad assumption but close enough for the distances upon which we consolidate)
        u, v, _ = e
        x, y = find_mean_node_position(G, [u, v])
        # Distance
        dist = np.sqrt((x - xMean) ** 2 + (y - yMean) ** 2)
        if dist < closestDist:
            closest = e
            closestDist = dist

    # In the case that no edge is found
    # Returns None
    # Calling function should stop action on receipt of this
    return closest


def consolidate_internal_graph_edges(
    graph: nx.MultiGraph, config: dict
) -> nx.MultiGraph:
    # min Length
    minLen = int(config.get("Min Length for Internal Line"))
    if minLen == 0:
        return graph
    # no nodes have been touched yet
    # Use this marking for the next step
    for n in graph.nodes():
        graph.nodes[n]["touch"] = False

    # get list of nodes, may change throughout looping due to pruning
    nodeList = list(graph.nodes()).copy()
    for n in nodeList:
        # Remove node from list, continue looping
        if n not in graph.nodes():
            continue

        node = graph.nodes[n]
        # Check if node has been touched
        if node["touch"] or len(graph.edges(n)) == 1:
            continue

        # Node has not been touched, continue
        # Loop for checking
        prev = 0
        while True:
            # Loop while there exists some edges that are below threshold
            # Might be worth adding a timeout
            while True:
                # Flood fill to find connected nodes wih sub threshold lengths
                connectedNodes, connectedEdges = flood_find(graph, n, minLen)
                # Check if there still exists edges that are below threshold in clump
                if not connectedEdges:
                    break

                # Find COM of clump
                COM = find_mean_node_position(graph, connectedNodes)

                # Find the edge that will be removed in the clump
                closestEdge = find_closest_edge_to_position(
                    graph, COM, connectedEdges, connectedNodes
                )
                # Get its weight, it will be later added to the connected nodes
                halfWeight = graph.edges[closestEdge]["weight"]

                # Extract nodes of closest edge, note u will be the remaining node
                u, v, _ = closestEdge
                # Determine new position of u
                # Determine middle entry of path and extract new position
                edgePath = graph.edges[closestEdge]["pts"]

                # Determine paths that will be added to remaining edges, take from graph edge
                paths = [edgePath[len(edgePath) // 2 :], edgePath[: len(edgePath) // 2]]
                midPoint = edgePath[len(edgePath) // 2]

                # Determine which edges connect to which node
                consolidatedEdges = [
                    graph.edges(u, keys=True),
                    [],  # Empty will be remade below
                ]  # v will reference u after contraction
                oldEdges = graph.edges(v, keys=True)
                for old in oldEdges:
                    new = tuple(u if x == v else x for x in old)
                    consolidatedEdges[1].append(new)

                # Combine Nodes, keep graph in place (no copy)
                nx.contracted_nodes(graph, u, v, self_loops=False, copy=False)
                # Reconstruct change u node position and edge info to fill missing
                # New u position
                graph.nodes[u]["o"] = midPoint
                # now for the modified edges
                for j in range(2):
                    nodePath = paths[j]
                    nodeEdges = consolidatedEdges[j]

                    # Take v's list and point it at u to get current reference

                    for edge in nodeEdges:
                        # Node will self reference as a result of deleted
                        if edge[0] == edge[1]:
                            continue
                        # Weight
                        graph.edges[edge]["weight"] = (
                            graph.edges[edge]["weight"] + halfWeight
                        )
                        # Path, order does not matter in the reconstruction process
                        # Check if only one entry and reshape if it is
                        if np.shape(nodePath) == (2,):
                            nodePath = np.array([nodePath])
                        graph.edges[edge]["pts"] = np.append(
                            graph.edges[edge]["pts"], nodePath, axis=0
                        )
            # Run through and check that all internal edges haven't been missed
            cont = True
            for edge in graph.edges(keys=True):
                if np.size(graph.edges[edge]["pts"]) < minLen:
                    # Make sure that the edges are internal
                    u, v, _ = edge
                    if len(graph.edges(u)) > 1 and len(graph.edges(v)) > 1:
                        count = len([e for e in graph.edges(keys=True) if  np.size(graph.edges[e]["pts"]) < minLen])
                        cont = prev == count
                        prev = count
                        break
            if cont:
                break

    return graph


def generate_skeleton_from_graph(shape: tuple, graph: nx.MultiGraph):
    skel = np.zeros(shape)
    # Plot every point on the graph on the new skeleton
    for e in graph.edges(keys=True):
        ps = graph.edges[e].get("pts")
        X = ps[:, 1]
        Y = ps[:, 0]
        for i in range(len(X)):
            skel[Y[i], X[i]] = 255
    for node in graph.nodes:
        ps = graph.nodes[node].get("o")
        x = ps[1]
        y = ps[0]
        skel[y, x] = 255
    return skel


def create_skeleton(segmentation, config):
    # Skeletonisation
    skel = skeletonize(segmentation)
    skelWidthPruned, skel_width = vessel_width_and_prune(skel, segmentation, config)
    graph = sknw.build_sknw(
        skelWidthPruned, multi=True, iso=False, ring=True, full=True
    )

    graphPruned = prune_skeleton_spurs_with_graph(graph, config)
    graphFinal = consolidate_internal_graph_edges(graphPruned, config)
    skelPruned = generate_skeleton_from_graph(np.shape(skel), graphFinal)

    return skelPruned, skel_width, graphFinal


def draw_and_save_images(image, segmentation, bp, ep, skel, name, config):
    save = bool(config.get("Save Image"))
    show = bool(config.get("Show Image"))
    if not save and not show:
        pass
    # io.imsave(name, segmentation)
    # Make an image
    masked = label2rgb(
        label(segmentation * 255),
        image=image,
        colors=["red"],
        kind="overlay",
        alpha=0.6,
        bg_label=0,
        bg_color=None,
        saturation=1,
    )
    # Mask skeleton
    maskedSkel = label2rgb(
        label(isotropic_dilation(skel * 255, 2)),
        image=masked,
        colors=["yellow"],
        kind="overlay",
        alpha=1,
        bg_label=0,
        bg_color=None,
        saturation=1,
    )
    #Convert to uint8
    maskedSkel = img_as_ubyte(maskedSkel).astype(np.uint8)
    radius = 5
    for point in bp:
        rr,cc = disk(point, radius, shape = maskedSkel.shape[:2])
        maskedSkel[rr,cc] = [0,0,255] #Blue (RGB Img)
    for point in ep:
        rr,cc = disk(point, radius, shape = maskedSkel.shape[:2])
        maskedSkel[rr,cc] = [0,255,0] #Blue (RGB Img)
    #Save and show image functionality
    if save or show:
        #Save image for later
        io.imsave(name, maskedSkel)
        
    

def obtain_branch_and_end_points(graph: nx.MultiGraph):
    branchPoints = []
    endPoints = []

    nodes = graph.nodes
    nodePs = np.array([nodes[i]["o"] for i in nodes])
    for i, node in enumerate(nodes):
        neighbours = sum(1 for _ in graph.neighbors(node))
        if neighbours == 1:
            # End Point
            endPoints.append([nodePs[i, 0], nodePs[i, 1]])

        elif neighbours > 2:
            # Branch Point
            branchPoints.append([nodePs[i, 0], nodePs[i, 1]])

    return (branchPoints, endPoints)


def vessel_statistics_from_graph(graph: nx.MultiGraph, skel):
    graphSum = 0
    for u, v, l in graph.edges:
        ps = graph.edges[(u, v, l)]["weight"]
        graphSum += ps

    totalLen = graphSum  # np.count_nonzero(skel)
    return totalLen, graphSum / len(graph.edges())

def process_image_results(i, segmentation, graph, skel, widthImage, imgName):
    try:
        results = {}
        results["Num"] = i
        results["Name"] = imgName
        branchPoints, endPoints = obtain_branch_and_end_points(graph)
        # Get number of cells
        results["Branch Points"] = len(branchPoints)
        results["End Points"] = len(endPoints)
        # Size of image
        imgSize = np.size(segmentation)
        # Area of Vessels
        results["vesselArea"] = np.count_nonzero(segmentation)
        # Percentage Area
        results["percentArea"] = results["vesselArea"] / imgSize * 100
        results["totalVesselLength"], results["avgVesselLength"] = (
            vessel_statistics_from_graph(graph, skel)
        )
        results["Avg Diameter"] = 2 * np.mean(widthImage[widthImage > 0])
        results["Errors"] = ""
    except Exception as e:
        results["Errors"] = str(e)
    return results, branchPoints, endPoints


def save_results_to_csv(savename, data):
    df = pd.DataFrame(data)
    df.to_csv(savename)


def run_img(image, resultsPath, config, saveName, i):
    try:
        print(f"RUNNING! - {image}")
        rgbimg, blurred = import_and_blur_image(image, config)
        segmentation = segment_image(blurred,config)
        eroded = isotropic_erosion(segmentation, 1)
        cleaned_segmentation = remove_holes_and_small_items(eroded, config)
        skel, width_im, graph = create_skeleton(cleaned_segmentation, config)
        img_results, branchPoints, endPoints = process_image_results(
            i, cleaned_segmentation, graph, skel, width_im, saveName
        )
        print(img_results)
        if config['Save Image'] or config['Show Image']:
            drawn_img = draw_and_save_images(
                rgbimg,
                cleaned_segmentation,
                branchPoints,
                endPoints,
                skel,
                os.path.abspath(str(resultsPath) + "\\" +saveName + ".tif"),
                config,
            )
        return img_results,
    except Exception as e:
        print(f"EXCEPTION: {e}")
        raise e


def worker_process(args):
    i, image, resultsPath, config = args
    imgName = os.path.basename(image)
    return run_img(image, resultsPath, config, imgName, i)

async def run_batch():
    pass


def main(configPath: str):
    startTime = time()
    configPath = Path(configPath)
    with open(configPath, "r") as file:
        config = yaml.safe_load(file)

    path = Path(config.get("Img Path"))
    savename = Path(config.get("Spreadsheet Output Path"))
    resultsPath = Path(config.get("Results Path"))

    images = find_images_in_path(path)
    results = []  # list of dictionaries
    args = [
        (i, image, resultsPath, config) for i, image in enumerate(images)
    ]

    set_start_method("spawn")
    with Pool(cpu_count()) as p:
        results = p.map(worker_process, args)
        p.close()
    # for arg in args:
    #     results.append(worker_process(arg))
    save_results_to_csv(savename, results)
    elapsed = time() - startTime
    print(f"Completed Processing in {elapsed} seconds")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Vascular Tool for Microscopy Analysis"
    )
    parser.add_argument("-c", "--config")
    parser.add_argument("-p", "--path")
    parser.add_argument("-s", "--savename")
    args = parser.parse_args()
    main(args.path, args.savename, None)
