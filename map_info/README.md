# Objectives 
This folder transfroms raw mobility GPS data to the map. You'll need to install couple of pip requirements and mongodb to write your data to. 

### types of datasets used in this work. 
Download the raw files from the following sites!
- t-drive (Beijing, China): [LINK](https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/)
- koln (Cologne, Germany): [LINK](http://kolntrace.project.citi-lab.fr/)
- geolife (Beijing, China): [LINK](https://www.microsoft.com/en-us/download/details.aspx?id=52367&from=https%3A%2F%2Fresearch.microsoft.com%2Fen-us%2Fdownloads%2Fb16d359d-d164-469e-9fd4-daa38f2b2e13%2F)
- porto (Porto, Portugal): [LINK](https://archive.ics.uci.edu/ml/datasets/Taxi+Service+Trajectory+-+Prediction+Challenge,+ECML+PKDD+2015)
- seoul (Seoul, South Korea) -> Simulated: [LINK](https://ieee-dataport.org/open-access/vehicular-mobility-trace-seoul-south-korea)

## {DATASET}_to_mdb.py files
these files reads from raw (lon, lat) coordinates and saves them to mongo db for later use.

## {DATASET}_visualization.py files
these files reads (lon, lat) coordinates from mongo db and plots them to streamlit

### plz add mapbox token in this folder to access maps.