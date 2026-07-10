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

    kml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<kml xmlns=\"http://www.opengis.net/kml/2.2\">"
        "<Document>"
        f"<name>{escape(doc_name)}</name>"
        + "".join(style_lines)
        + f"<Folder><name>{escape(folder_name)}</name>"
        + "".join(placemark_lines)
        + "</Folder></Document></kml>"
    )
    return kml
