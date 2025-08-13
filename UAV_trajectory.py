import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# --- Helper: start a local HTTP server and open the HTML ---
def _serve_and_open(out_html, port=8000):
    import http.server, socketserver, threading, webbrowser, pathlib, time
    html_path = pathlib.Path(out_html).resolve()
    directory = str(html_path.parent)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

    # try a range of ports in case one is busy
    for p in range(port, port + 10):
        try:
            httpd = socketserver.TCPServer(("", p), Handler)
            port = p
            break
        except OSError:
            continue

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    url = f"http://localhost:{port}/{html_path.name}"
    webbrowser.open(url)
    print(f"[Cesium] Serving {directory} → {url} (Ctrl+C to stop)")
    time.sleep(1.0)

# Ion token (fine to keep — not required for OSM-only setup)
CESIUM_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIyMWRhNWQwZS0zYjhkLTQ3MDQtOGJjYy1hZDlkY2QxZTVlYzIiLCJpZCI6MzMxMDQ3LCJpYXQiOjE3NTQ5NjgyOTB9.6L2x2C1XMH2oX7hRHV_6lZWwG8YD_KbjklkL1Xn37p4"
if CESIUM_TOKEN:
    os.environ["CESIUM_ION_TOKEN"] = CESIUM_TOKEN

# Load the CSV file
file_path = os.path.expanduser('~/Downloads/uav_navigation_dataset.csv')
df = pd.read_csv(file_path)

# Show the first few rows
print("=== UAV Trajectory Preview ===")
print(df.head())

# Show column names and basic info
print("\n=== Data Summary ===")
print(df.info())
df = df.sort_values(by='timestamp')

# ---------- Plotly 2D ----------
fig_2D = px.scatter_mapbox(
    df,
    lat='latitude',
    lon='longitude',
    color='altitude',
    hover_name='timestamp',
    zoom=13,
    height=600
)
fig_2D.update_layout(mapbox_style="open-street-map")
fig_2D.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
fig_2D.show()

# ---------- Plotly 3D ----------
fig_3D = go.Figure(data=[go.Scatter3d(
    x=df['longitude'],
    y=df['latitude'],
    z=df['altitude'],
    mode='lines+markers',
    marker=dict(
        size=3,
        color=df['altitude'],
        colorscale='Viridis',
        opacity=0.8,
        colorbar=dict(title='Altitude')
    ),
    line=dict(color='blue', width=2)
)])
fig_3D.update_layout(
    title='3D UAV Flight Trajectory',
    scene=dict(
        xaxis_title='Longitude',
        yaxis_title='Latitude',
        zaxis_title='Altitude',
        aspectmode='manual',
        aspectratio=dict(x=1, y=1, z=0.3)
    ),
    height=700,
    margin=dict(r=0, t=0, l=0, b=0)
)
fig_3D.show()

# ---------- Dash (click to continue) ----------
from dash import Dash, dcc, html, Input, Output
import plotly.graph_objs as go

app = Dash(__name__)

def create_3d_figure(selected_index=None):
    df_anim = df.iloc[selected_index:] if selected_index is not None else df
    fig = go.Figure(data=[
        go.Scatter3d(
            x=df_anim['longitude'],
            y=df_anim['latitude'],
            z=df_anim['altitude'],
            mode='lines+markers',
            marker=dict(
                size=3,
                color=df_anim['altitude'],
                colorscale='Viridis',
                opacity=0.8
            ),
            line=dict(color='blue', width=2)
        )
    ])
    fig.update_layout(
        title='Interactive UAV 3D Trajectory',
        scene=dict(
            xaxis_title='Longitude',
            yaxis_title='Latitude',
            zaxis_title='Altitude',
            aspectmode='manual',
            aspectratio=dict(x=1, y=1, z=0.3)
        ),
        height=700
    )
    return fig

app.layout = html.Div([
    html.H1("Click on a point to view next trajectory steps"),
    dcc.Graph(id='trajectory-3d', figure=create_3d_figure(), style={'height': '700px'})
])

@app.callback(
    Output('trajectory-3d', 'figure'),
    Input('trajectory-3d', 'clickData')
)
def update_trajectory(clickData):
    if clickData is None:
        return create_3d_figure()
    point_index = clickData['points'][0]['pointIndex']
    return create_3d_figure(point_index)

# ---------- CesiumJS 3D Globe Export ----------
def export_cesium_html(df, out_html="uav_3d_globe.html", ion_token="", sample_step=5):
    # Downsample to reduce HTML size
    dfd = df.iloc[::max(1, int(sample_step))].reset_index(drop=True)
    for col in ["longitude", "latitude", "altitude"]:
        if col not in dfd.columns:
            raise ValueError(f"Missing required column: {col}")

    # Flat [lon,lat,alt] list
    pos_list = []
    for _, r in dfd.iterrows():
        pos_list.extend([float(r["longitude"]), float(r["latitude"]), float(r["altitude"])])
    positions_js = ",".join([str(x) for x in pos_list])

    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>UAV 3D Globe (Cesium)</title>
  <style>html, body, #cesiumContainer {width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden;}</style>
  <script src="https://unpkg.com/cesium@1.121/Build/Cesium/Cesium.js"></script>
  <link href="https://unpkg.com/cesium@1.121/Build/Cesium/Widgets/widgets.css" rel="stylesheet">
</head>
<body>
  <div id="cesiumContainer"></div>
  <script>
    // --- Token & imagery/terrain setup with robust fallbacks ---
    Cesium.Ion.defaultAccessToken = "__ION_TOKEN__"; // it's fine if empty
    const hasToken = "__ION_TOKEN__".trim().length > 0;

    // Helper: swap to OpenStreetMap tiles
    function useOSM(reason) {
      console.warn('Falling back to OSM imagery:', reason || '');
      try {
        const osm = new Cesium.UrlTemplateImageryProvider({
          url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          credit: '© OpenStreetMap contributors'
        });
        viewer.imageryLayers.removeAll();
        viewer.imageryLayers.addImageryProvider(osm);
      } catch (e) {
        console.error('OSM fallback failed:', e);
      }
    }

    // Create the viewer first with a neutral configuration;
    // we will attach imagery right after so we can fallback if needed.
    const viewer = new Cesium.Viewer('cesiumContainer', {
      baseLayerPicker: false,     // lock imagery to the chosen provider
      geocoder: false,
      animation: true,
      timeline: true,
      terrain: hasToken ? Cesium.Terrain.fromWorldTerrain() : undefined
    });

    // Ensure a globe is present and visible
    if (!viewer.scene.globe) {
      viewer.scene.globe = new Cesium.Globe(Cesium.Ellipsoid.WGS84);
    }
    viewer.scene.globe.show = true;
    // Make sure geometry isn't hidden by terrain depth testing
    viewer.scene.globe.depthTestAgainstTerrain = false;
    // Optional atmosphere; wrap in try so older/newer builds don't break
    try { viewer.scene.skyAtmosphere = new Cesium.SkyAtmosphere(); } catch (e) {}
    // Avoid SkyBox.createDefaultCubeMap() which is not available in some Cesium builds
    viewer.scene.skyBox = undefined;

    // Prefer Cesium World Imagery (satellite) when token is present; fallback to OSM
    try {
      viewer.imageryLayers.removeAll();
      if (hasToken) {
        try {
          viewer.imageryLayers.addImageryProvider(
            new Cesium.IonImageryProvider({ assetId: 2 }) // Cesium World Imagery (satellite)
          );
        } catch (e) {
          console.warn('Ion imagery failed, falling back to OSM:', e);
          viewer.imageryLayers.addImageryProvider(
            new Cesium.UrlTemplateImageryProvider({
              url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              credit: '© OpenStreetMap contributors'
            })
          );
        }
      } else {
        viewer.imageryLayers.addImageryProvider(
          new Cesium.UrlTemplateImageryProvider({
            url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
            credit: '© OpenStreetMap contributors'
          })
        );
      }
    } catch (e) {
      console.warn('Imagery setup error:', e);
    }

    // ---- 3D base: world terrain + OSM 3D Buildings (requires Ion token) ----
    try {
      if (hasToken) {
        // Prefer newer API if available; otherwise, keep earlier syntax
        if (Cesium.Terrain && Cesium.Terrain.fromWorldTerrain) {
          viewer.terrainProvider = Cesium.Terrain.fromWorldTerrain();
        } else if (Cesium.CesiumTerrainProvider && Cesium.IonResource) {
          viewer.terrainProvider = new Cesium.CesiumTerrainProvider({
            url: Cesium.IonResource.fromAssetId(1)
          });
        }

        // Add OSM 3D Buildings – API name differs across Cesium versions
        const addOSMBuildings = () => {
          try {
            if (Cesium.createOsmBuildingsAsync) {
              Cesium.createOsmBuildingsAsync().then(ts => {
                viewer.scene.primitives.add(ts);
              });
            } else if (Cesium.createOsmBuildings) {
              viewer.scene.primitives.add(Cesium.createOsmBuildings());
            }
          } catch (e) {
            console.warn('OSM Buildings not available:', e);
          }
        };
        addOSMBuildings();

        // Lighting/shadows to enhance 3D appearance
        viewer.scene.globe.enableLighting = true;
        viewer.shadows = true;
      }
    } catch (e) {
      console.warn('Terrain/Buildings setup failed:', e);
    }

    // -------- Build UAV positions, path, and animated entity (more visible) --------
    const flat = [__POSITIONS__];  // [lon,lat,alt, ...]
    console.log("Flat coords length:", flat.length, "First 6:", flat.slice(0, 6));
    const positions = [];
    for (let i = 0; i < flat.length; i += 3) {
      const lon = Number(flat[i]);
      const lat = Number(flat[i + 1]);
      const altRaw = Number(flat[i + 2]);
      if (!isFinite(lon) || !isFinite(lat)) continue;
      if (lon < -180 || lon > 180 || lat < -90 || lat > 90) continue;
      // lift by +30 m to ensure visibility above ground imagery/terrain
      const alt = (isFinite(altRaw) ? altRaw : 0) + 30.0;
      positions.push(Cesium.Cartesian3.fromDegrees(lon, lat, alt));
    }
    console.log("Valid UAV positions:", positions.length);
    if (positions.length === 0) {
      console.warn("No valid UAV positions parsed from CSV.");
    }

    // Static path line (so you always see a track)
    const pathEntity = viewer.entities.add({
      id: 'uav-path',
      name: 'UAV Path',
      polyline: {
        positions: positions,
        width: 4,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.25,
          color: Cesium.Color.CYAN
        })
      }
    });
    viewer.zoomTo(pathEntity);

    // Animated point along the path
    const start = Cesium.JulianDate.now();
    const posProp = new Cesium.SampledPositionProperty();
    for (let i = 0; i < positions.length; i++) {
      const t = Cesium.JulianDate.addSeconds(start, i, new Cesium.JulianDate());
      posProp.addSample(t, positions[i]);
    }

    const uav = viewer.entities.add({
      id: 'uav',
      name: 'UAV',
      position: posProp,
      point: { pixelSize: 14, color: Cesium.Color.RED, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
      path: {
        trailTime: Math.max(positions.length, 300),  // show long trail
        leadTime: 0,
        width: 4,
        material: new Cesium.PolylineGlowMaterialProperty({
          glowPower: 0.3,
          color: Cesium.Color.YELLOW
        })
      }
    });

    // Center camera on full track
    try {
      const bs = Cesium.BoundingSphere.fromPoints(positions);
      viewer.scene.camera.flyToBoundingSphere(bs, { duration: 1.2 });
    } catch (e) {
      viewer.zoomTo(viewer.entities);
    }

    // Clock and camera
    viewer.clock.startTime   = start.clone();
    viewer.clock.stopTime    = Cesium.JulianDate.addSeconds(start, positions.length, new Cesium.JulianDate());
    viewer.clock.currentTime = start.clone();
    viewer.clock.clockRange  = Cesium.ClockRange.CLAMPED;
    viewer.clock.multiplier  = 10;
    viewer.clock.shouldAnimate = true;
  </script>
</body>
</html>
"""
    html = html.replace("__ION_TOKEN__", ion_token).replace("__POSITIONS__", positions_js)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[Cesium] Wrote 3D globe to: {out_html}")

    # Focus camera on first point
    if not dfd.empty:
        start_lat = float(dfd['latitude'].iloc[0])
        start_lon = float(dfd['longitude'].iloc[0])
        start_alt = float(dfd['altitude'].iloc[0])
        camera_script = """
<script>
  viewer.camera.flyTo({ destination : Cesium.Cartesian3.fromDegrees(__LON__, __LAT__, Math.max(50.0, __ALT__) + 300), duration: 3 });
</script>
""".replace("__LON__", str(start_lon)).replace("__LAT__", str(start_lat)).replace("__ALT__", str(start_alt))
        with open(out_html, "r", encoding="utf-8") as f:
            html_data = f.read()
        html_data = html_data.replace("</body>", camera_script + "\n</body>")
        with open(out_html, "w", encoding="utf-8") as f:
            f.write(html_data)
        print(f"[Cesium] Updated camera to start at ({start_lat}, {start_lon})")

    # Serve over HTTP and open
    try:
        _serve_and_open(out_html, port=8000)
    except Exception as e:
        print(f"[Cesium] Could not start local server: {e}")

# ---------- Run exporter ----------
if __name__ == "__main__":
    ion = os.environ.get("CESIUM_ION_TOKEN", "")
    export_cesium_html(df, out_html="uav_3d_globe.html", ion_token=ion, sample_step=5)