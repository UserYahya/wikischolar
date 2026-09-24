"""Static files with content-hashed names (cache busting) that never break a page."""
from whitenoise.storage import CompressedManifestStaticFilesStorage


class ForgivingManifestStorage(CompressedManifestStaticFilesStorage):
    """Serves app.3f2a….css so browsers pick up new CSS/JS after every update. If `collectstatic`
    was forgotten after an upload, a file missing from the manifest falls back to its plain name
    (possibly stale or 404) instead of failing the whole page with error 500."""
    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name
