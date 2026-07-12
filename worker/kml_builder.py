from __future__ import annotations

from xml.sax.saxutils import escape


def _hail_color_aabbggrr(hail_mm: float, min_mm: float = 19.0, max_mm: float = 80.0) -> str:
    # Darker red for larger hail: keep red at max, decrease green/blue as hail increases.
    if max_mm <= min_mm:
        ratio = 1.0
    else:
        ratio = (hail_mm - min_mm) / (max_mm - min_mm)
    ratio = max(0.0, min(1.0, ratio))

    gb = int(round(220 - (220 * ratio)))
    # Returns bbggrr component; alpha is applied separately per style target.
    return f"{gb:02x}{gb:02x}ff"


def build_hail_swath_kml(
    cells: list[tuple[float, float, float]],
    region_name: str,
    event_date: str,
    folder_name: str = "Damage Map",
    cell_size_deg: float = 0.01,
    canvass_targets: list[dict] | None = None,
    dealership_hits: list[dict] | None = None,
) -> str:
    doc_name = f"{region_name} damage map {event_date}"
    half = cell_size_deg / 2.0

    style_lines = []
    placemark_lines = []

    for idx, (lat, lon, hail_mm) in enumerate(cells, start=1):
        style_id = f"cell-style-{idx}"
        bbggrr = _hail_color_aabbggrr(hail_mm)
        fill_color = f"4D{bbggrr}"
        line_color = f"B3{bbggrr}"

        min_lat = lat - half
        max_lat = lat + half
        min_lon = lon - half
        max_lon = lon + half

        style_lines.append(
            f"<Style id=\"{style_id}\"><LineStyle><color>{line_color}</color><width>1</width></LineStyle>"
            f"<PolyStyle><color>{fill_color}</color><fill>1</fill><outline>1</outline></PolyStyle></Style>"
        )

        placemark_lines.append(
            "<Placemark>"
            f"<name>{hail_mm:.2f} mm</name>"
            f"<description>{escape(f'lat={lat:.4f}, lon={lon:.4f}, hail={hail_mm:.2f} mm')}</description>"
            f"<styleUrl>#{style_id}</styleUrl>"
            "<Polygon><outerBoundaryIs><LinearRing><coordinates>"
            f"{min_lon:.6f},{min_lat:.6f},0 "
            f"{max_lon:.6f},{min_lat:.6f},0 "
            f"{max_lon:.6f},{max_lat:.6f},0 "
            f"{min_lon:.6f},{max_lat:.6f},0 "
            f"{min_lon:.6f},{min_lat:.6f},0"
            "</coordinates></LinearRing></outerBoundaryIs></Polygon>"
            "</Placemark>"
        )

    targets_style = (
        "<Style id=\"canvass-pin\">"
        "<IconStyle><scale>1.1</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/red-circle.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>1.0</scale></LabelStyle>"
        "</Style>"
    )

    target_lines = []
    for target in canvass_targets or []:
        lat = float(target.get("centroid_lat") or 0.0)
        lon = float(target.get("centroid_lon") or 0.0)
        rank = int(target.get("rank") or 0)
        score = int(target.get("score") or 0)
        tag = str(target.get("profile_tag") or "target")
        hail_in = float(target.get("hail_in") or 0.0)
        geoid = str(target.get("geoid") or "")
        name = f"#{rank} [score {score}] {tag} — {hail_in:.1f}in"
        description = f"GEOID {geoid}; hail {hail_in:.2f} in; profile {tag}; score {score}"
        target_lines.append(
            "<Placemark>"
            f"<name>{escape(name)}</name>"
            f"<description>{escape(description)}</description>"
            "<styleUrl>#canvass-pin</styleUrl>"
            f"<Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point>"
            "</Placemark>"
        )

    targets_folder = ""
    if target_lines:
        targets_folder = (
            "<Folder><name>Canvass Targets</name>"
            + "".join(target_lines)
            + "</Folder>"
        )

    dealership_style = (
        "<Style id=\"dealership-pin\">"
        "<IconStyle><scale>1.1</scale><Icon><href>http://maps.google.com/mapfiles/kml/paddle/wht-blank.png</href></Icon></IconStyle>"
        "<LabelStyle><scale>1.0</scale></LabelStyle>"
        "</Style>"
    )

    dealership_lines = []
    for hit in dealership_hits or []:
        lat = float(hit.get("lat") or 0.0)
        lon = float(hit.get("lon") or 0.0)
        name = str(hit.get("name") or "Dealership")
        hail_in = float(hit.get("hail_in") or 0.0)
        brand = str(hit.get("brand") or "")
        label = f"{name} — {hail_in:.1f}in"
        description = f"{name}; brand={brand or 'n/a'}; hail={hail_in:.2f} in"
        dealership_lines.append(
            "<Placemark>"
            f"<name>{escape(label)}</name>"
            f"<description>{escape(description)}</description>"
            "<styleUrl>#dealership-pin</styleUrl>"
            f"<Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point>"
            "</Placemark>"
        )

    dealerships_folder = ""
    if dealership_lines:
        dealerships_folder = (
            "<Folder><name>Dealership Hits</name>"
            + "".join(dealership_lines)
            + "</Folder>"
        )

    kml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<kml xmlns=\"http://www.opengis.net/kml/2.2\">"
        "<Document>"
        f"<name>{escape(doc_name)}</name>"
        + targets_style
        + dealership_style
        + "".join(style_lines)
        + f"<Folder><name>{escape(folder_name)}</name>"
        + "".join(placemark_lines)
        + "</Folder>"
        + targets_folder
        + dealerships_folder
        + "</Document></kml>"
    )
    return kml
