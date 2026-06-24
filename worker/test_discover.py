from hail_engine import resolve_latest_mesh_url

if __name__ == "__main__":
    url = resolve_latest_mesh_url("https://thredds.ncep.noaa.gov/thredds/fileServer/meso_analyses/merged/mesh/")
    print(url)
