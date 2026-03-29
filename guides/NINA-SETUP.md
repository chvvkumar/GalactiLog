# N.I.N.A. Setup Guide

This guide covers how to configure N.I.N.A. (Nighttime Imaging 'N' Astronomy) so that GalactiLog can extract the maximum amount of data from your imaging sessions.

## Overview

GalactiLog reads data from three sources produced by N.I.N.A.:

1. **FITS file headers** -- Metadata embedded in every captured frame (always available)
2. **ImageMetaData.csv** -- Per-frame quality and equipment metrics exported by N.I.N.A. during a session
3. **WeatherData.csv** -- Environmental data logged by a connected weather source

Only FITS files are required. The CSV files are optional but provide significantly more detailed analytics.

## Required: FITS Output Settings

GalactiLog reads the following FITS headers. N.I.N.A. writes most of these by default when saving FITS files.

| FITS Header | Description | Used For |
|-------------|-------------|----------|
| `OBJECT` | Target name (e.g., "M31", "NGC 7000") | Target resolution via SIMBAD |
| `IMAGETYP` | Frame type: LIGHT, DARK, FLAT, BIAS | Frame classification, calibration filtering |
| `EXPTIME` | Exposure duration in seconds | Integration time calculations |
| `FILTER` | Optical filter name (e.g., "Ha", "OIII", "L") | Filter usage analytics, palette display |
| `INSTRUME` | Camera model | Equipment tracking |
| `TELESCOP` | Telescope/optics | Equipment tracking |
| `CCD-TEMP` | Sensor temperature in Celsius | Environmental monitoring |
| `GAIN` | Camera gain setting | Equipment metrics |
| `DATE-OBS` | Observation timestamp (ISO 8601) | Session grouping, timeline |
| `HFR` | Half-Flux Radius | Focus quality metric |
| `FWHM` / `MEANFWHM` | Full Width at Half Maximum | Star quality metric |
| `ECCENTRICITY` / `ELLIPTICITY` | Star elongation | Guiding/tracking quality |

### File Format

- Save as FITS format (`.fits`, `.fit`, or `.fts` extensions)
- GalactiLog reads the primary HDU (extension 0) headers
- All standard N.I.N.A. FITS output settings work without modification

### File Naming

GalactiLog can extract HFR from N.I.N.A.'s default filename pattern. If your filenames include the HFR value (e.g., `M31_Light_Ha_300s_1.56HFR_2025-01-15.fits`), it will be parsed as a fallback when the FITS header does not contain an HFR value.

## Optional: ImageMetaData.csv

N.I.N.A. can export a CSV file with per-frame metrics alongside your FITS files. This provides GalactiLog with detailed quality data that is not available in FITS headers alone.

### What It Provides

| Metric | Description |
|--------|-------------|
| HFR Stdev | Standard deviation of Half-Flux Radius across detected stars |
| FWHM | Full Width at Half Maximum |
| Detected Stars | Number of stars detected in the frame |
| Guiding RMS | Total guiding error in arcseconds |
| Guiding RMS RA | Right Ascension guiding error |
| Guiding RMS Dec | Declination guiding error |
| ADU Mean | Mean pixel value |
| ADU Median | Median pixel value |
| ADU Stdev | Standard deviation of pixel values |
| ADU Min / Max | Pixel value range |
| Focuser Position | Focuser step position |
| Focuser Temperature | Temperature at focuser |
| Rotator Position | Camera rotation angle |
| Pier Side | Mount pier side (East/West) |
| Airmass | Atmospheric airmass value |

### Enabling CSV Export

In N.I.N.A., the ImageMetaData.csv is written automatically during imaging sequences. The file is placed in the same directory as your FITS files.

GalactiLog looks for `ImageMetaData.csv` in the same directory as each FITS file. The CSV filenames are matched to FITS files by the image filename column.

### Directory Placement

The CSV file must be in the same directory as the FITS files:

```
/astro_incoming/
  M31/
    2025-01-15/
      ImageMetaData.csv          <-- Found by GalactiLog
      M31_Light_Ha_300s_001.fits
      M31_Light_Ha_300s_002.fits
```

## Optional: WeatherData.csv

If you have a weather source connected to N.I.N.A. (either a hardware weather station or a plugin like OpenWeatherMap), N.I.N.A. logs environmental conditions to a WeatherData.csv file.

### What It Provides

| Metric | Description |
|--------|-------------|
| Ambient Temperature | Air temperature in Celsius |
| Humidity | Relative humidity percentage |
| Dew Point | Dew point temperature |
| Pressure | Atmospheric pressure |
| Wind Speed | Wind speed |
| Wind Direction | Wind direction in degrees |
| Wind Gust | Peak wind gust speed |
| Cloud Cover | Cloud coverage percentage |
| Sky Quality | Sky quality meter reading (mag/arcsec^2) |

### Weather Sources

Any weather source compatible with N.I.N.A. will work:

- **OpenWeatherMap Plugin** -- Free API-based weather data (requires API key)
- **Pegasus Ultimate Powerbox** -- Integrated environmental sensors
- **AAG CloudWatcher** -- Cloud and rain detection
- **Davis Instruments** -- Weather station hardware
- **Other ASCOM weather drivers** -- Any ASCOM-compatible weather station

## Recommended N.I.N.A. Plugins

The following table summarizes which N.I.N.A. components and plugins produce data that GalactiLog can use:

| Plugin / Component | Type | Metrics for GalactiLog |
|-------------------|------|----------------------|
| **N.I.N.A. Core** | Built-in | FITS headers (object, exposure, filter, camera, telescope, gain, sensor temp, date) |
| **N.I.N.A. HFR/Star Analysis** | Built-in | HFR, FWHM, eccentricity, detected stars (via FITS headers and CSV) |
| **PHD2 Guiding** | External | Guiding RMS total/RA/Dec (written to ImageMetaData.csv) |
| **N.I.N.A. Internal Guider** | Built-in | Guiding RMS (written to ImageMetaData.csv) |
| **OpenWeatherMap** | Plugin | Ambient temp, humidity, dew point, pressure, wind, cloud cover |
| **Weather Station** (ASCOM) | Hardware | Full environmental data suite via WeatherData.csv |
| **Hocus Focus** | Plugin | Improved autofocus metrics, focuser temperature tracking |
| **Ground Station** | Plugin | Enhanced environmental monitoring |

## Directory Structure

GalactiLog scans your FITS directory recursively. It works with any directory structure, but a typical N.I.N.A. layout looks like this:

```
/astro_incoming/                        <-- FITS_DATA_HOST_PATH
  M31 - Andromeda Galaxy/
    2025-01-15/
      M31_Light_Ha_300s_001.fits
      M31_Light_Ha_300s_002.fits
      M31_Dark_300s_001.fits
      ImageMetaData.csv
    2025-01-20/
      M31_Light_OIII_300s_001.fits
      ImageMetaData.csv
  NGC 7000/
    2025-02-10/
      NGC7000_Light_SII_300s_001.fits
      ImageMetaData.csv
      WeatherData.csv
```

Key points:
- GalactiLog scans for `.fits`, `.fit`, and `.fts` files (case-insensitive)
- Subdirectory depth and naming do not matter
- Calibration frames (DARK, FLAT, BIAS) are detected by the `IMAGETYP` FITS header
- CSV files must be in the same directory as the FITS files they describe
