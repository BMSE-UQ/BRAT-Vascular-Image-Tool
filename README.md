# BRAT - Batch Resourcing Angiogeneis Tool
BRAT is a tool for analysis of microscope images of micro-vascular networks and similar structures. Its role is to take images of these structures and create statistics that can be useful for a scientific researcher.


**Link to the preprint:** [BioRxiv](https://doi.org/10.1101/2025.01.24.634836)

**To Install, please see the "Releases" section on the right-hand side. Click there and the latest release will be available in .exe form**

## Statistics Generated
|*Statistic*|*Description*|
|---|---|
|Branch Point|Number of points where the vessels branch off|
|End Point|Number of Points where the vessel engs|
|vesselArea|Area taken up by the imaged network|
|percentArea|Percentage of the total area of image taken by the vessel area|
|totalVesselLength|Total length of all vessels in a given image|
|avgVesselLength|Average lenght of all vessels in a given image|
|avg Diameter|Average diameter of all vessels in a given image|

## BRAT CLI
To increase speed without the overhead of the gui, the BRAT CLI can be used to increase processing speed. To use BRAT CLI, simply setup a config and save it. Then run the following command:
```
brat.exe --config \\path\\to\\config
```

## Issues With BRAT
Please report any bugs/issues/suggestions found with BRAT via our [Github issues page](https://github.com/BMSE-UQ/BRAT-Vascular-Image-Tool/issues).