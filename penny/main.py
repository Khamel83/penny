"""Penny - Your personal voice assistant."""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import classifier, database
from .models import (
    IngestRequest,
    Item,
    ItemResponse,
    ItemsResponse,
    ReclassifyRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    await database.init_db()
    yield


app = FastAPI(
    title="Penny",
    description="Your personal voice assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "penny"}


@app.post("/api/ingest", response_model=ItemResponse)
async def ingest(request: IngestRequest):
    """Ingest transcribed text, classify it, and route to appropriate service."""
    # Classify the text (returns dict with classification + routing data)
    result = classifier.classify(request.text)
    classification = result.get("classification", "unknown")
    confidence = result.get("confidence", 0.0)

    # Create the item
    item = Item(
        text=request.text,
        classification=classification,
        confidence=confidence,
        source_file=request.source_file,
        created_at=request.timestamp or datetime.utcnow(),
    )

    # Save to database first
    saved_item = await database.save_item(item)

    # Route to appropriate service (if router is available)
    routed_to = None
    route_error = None
    try:
        from . import router
        route_result = await router.route(classification, request.text, result)
        if route_result.get("routed"):
            routed_to = route_result.get("service")
            # Update item with routing info
            await database.update_routed_to(saved_item.id, routed_to)
            saved_item.routed_to = routed_to
        elif route_result.get("error"):
            route_error = route_result.get("error")
    except ImportError:
        # Router not yet implemented, that's OK
        pass
    except Exception as e:
        route_error = str(e)

    message = f"Classified as {classification}"
    if routed_to:
        message += f", routed to {routed_to}"
    elif route_error:
        message += f" (routing failed: {route_error})"

    return ItemResponse(item=saved_item, message=message)


@app.get("/api/items", response_model=ItemsResponse)
async def get_items(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    classification: Optional[str] = Query(None, pattern="^(work|personal|shopping|media|smart_home|unknown)$"),
):
    """Get paginated list of items."""
    items, total = await database.get_items(page, per_page, classification)
    return ItemsResponse(items=items, total=total, page=page, per_page=per_page)


@app.post("/api/items/{item_id}/reclassify", response_model=ItemResponse)
async def reclassify(item_id: str, request: ReclassifyRequest):
    """Reclassify an item."""
    item = await database.update_classification(item_id, request.classification)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemResponse(item=item, message=f"Reclassified to {request.classification}")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the web UI."""
    # Get recent items
    items, total = await database.get_items(page=1, per_page=50)

    # Build HTML
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Penny</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header>
        <div class="header-content">
            <div class="logo">P</div>
            <div>
                <h1>Penny</h1>
                <p class="subtitle">Your personal voice assistant</p>
            </div>
        </div>
    </header>

    <main>
        <section class="stats">
            <div class="stat-box">
                <span class="stat-number">""" + str(total) + """</span>
                <span class="stat-label">Total items</span>
            </div>
        </section>

        <section class="filters">
            <button class="filter-btn active" onclick="filterItems('')">All</button>
            <button class="filter-btn" onclick="filterItems('shopping')">🛒 Shopping</button>
            <button class="filter-btn" onclick="filterItems('media')">🎬 Media</button>
            <button class="filter-btn" onclick="filterItems('work')">📋 Work</button>
            <button class="filter-btn" onclick="filterItems('smart_home')">🏠 Home</button>
            <button class="filter-btn" onclick="filterItems('personal')">💭 Personal</button>
        </section>

        <section class="add-form">
            <form onsubmit="addItem(event)">
                <div class="add-form-row">
                    <input type="text" id="new-item-text" placeholder="Add a note..." class="add-input" required>
                    <button type="submit" class="add-btn">Add</button>
                </div>
            </form>
        </section>

        <section id="items-list" class="items">
"""

    if not items:
        html += """
            <div class="empty-state">
                <div class="empty-state-icon">🎙️</div>
                <h2>No voice memos yet</h2>
                <p>Record a voice memo on your iPhone or Apple Watch to get started.</p>
                <p class="hint">Make sure iCloud Voice Memos sync is enabled</p>
            </div>
"""
    else:
        for item in items:
            badge_class = f"badge-{item.classification}"
            created = item.created_at.strftime("%b %d, %H:%M")
            # Build routing indicator
            routed_html = ""
            if item.routed_to:
                routed_html = f'<span class="routed-to {item.routed_to}">{item.routed_to}</span>'
            html += f"""
            <article class="item {item.classification}" data-id="{item.id}">
                <div class="item-header">
                    <div style="display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap;">
                        <span class="badge {badge_class}">{item.classification}</span>
                        {routed_html}
                    </div>
                    <time>{created}</time>
                </div>
                <p class="item-text">{item.text}</p>
                <div class="item-actions">
                    <select onchange="reclassify('{item.id}', this.value)" class="reclassify-select">
                        <option value="">Reclassify...</option>
                        <option value="shopping">Shopping</option>
                        <option value="media">Media</option>
                        <option value="work">Work</option>
                        <option value="smart_home">Smart Home</option>
                        <option value="personal">Personal</option>
                        <option value="unknown">Unknown</option>
                    </select>
                </div>
            </article>
"""

    html += """
        </section>
    </main>

    <script>
        function filterItems(classification) {
            const url = classification ? `/api/items?classification=${classification}` : '/api/items';
            fetch(url)
                .then(r => r.json())
                .then(data => {
                    // Update button states
                    document.querySelectorAll('.filter-btn').forEach(btn => {
                        btn.classList.remove('active');
                        if (btn.textContent.toLowerCase() === classification ||
                            (classification === '' && btn.textContent === 'All')) {
                            btn.classList.add('active');
                        }
                    });
                    // Reload page to show filtered items
                    location.reload();
                });
        }

        function reclassify(itemId, classification) {
            if (!classification) return;
            fetch(`/api/items/${itemId}/reclassify`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({classification})
            })
            .then(r => r.json())
            .then(() => location.reload());
        }

        function addItem(event) {
            event.preventDefault();
            const input = document.getElementById('new-item-text');
            const text = input.value.trim();
            if (!text) return;

            fetch('/api/ingest', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    text: text,
                    source_file: 'manual-entry',
                    timestamp: new Date().toISOString()
                })
            })
            .then(r => r.json())
            .then(() => {
                input.value = '';
                location.reload();
            });
        }
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
