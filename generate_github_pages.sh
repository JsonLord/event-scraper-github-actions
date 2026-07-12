#!/bin/bash
# Generate GitHub Pages content from events database

# Exit on any error
set -e

echo "Generating GitHub Pages content..."

# Create docs directory if it doesn't exist
mkdir -p docs

# Export events from SQLite database to JSON for the frontend
if [ -f "data/events.db" ]; then
  echo "Exporting events from database..."
  sqlite3 data/events.db "SELECT title, date, time, price, category, description, source_url FROM events WHERE date >= date('now', '-7 days') ORDER BY date, time;" > docs/events.json || echo "Warning: Could not export events, creating empty array"
  
  # If the file is empty or invalid, create an empty array
  if [ ! -s "docs/events.json" ] || ! jq -e . docs/events.json >/dev/null 2>&1; then
    echo "[]" > docs/events.json
  fi
else
  echo "No events database found, creating empty events array"
  echo "[]" > docs/events.json
fi

# Create a simple index.html to display the events
cat > docs/index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Berlin Events - Free & Affordable</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        /* Custom styles */
        .event-card {
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .event-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }
        .price-free { color: #10b981; }
        .price-paid { color: #f59e0b; }
        .price-unknown { color: #6b7280; }
    </style>
</head>
<body class="bg-gray-="bg-gray-50 min-h-screen">
    <div class="container mx-auto px-4 py-8">
        <header class="text-center mb-12">
            <h1 class="text-4xl font-bold text-gray-800 mb-2">Berlin Events</h1>
            <p class="text-lg text-gray-600">Free & Affordable Events (≤15€)</p>
            <div class="mt-4">
                <span id="last-updated" class="bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm font-medium">Loading...</span>
            </div>
        </header>

        <!-- Stats -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <div class="bg-white p-4 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-800">Total Events</h3>
                <p class="text-3xl font-bold text-blue-600" id="total-count">0</p>
            </div>
            <div class="bg-white p-4 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-800">Free Events</h3>
                <p class="text-3xl font-bold text-green-600" id="free-count">0</p>
            </div>
            <div class="bg-white p-4 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-800">Paid Events</h3>
                <p class="text-3xl font-bold text-yellow-600" id="paid-count">0</p>
            </div>
            <div class="bg-white p-4 rounded-lg shadow">
                <h3 class="text-lg font-semibold text-gray-800">This Weekend</h3>
                <p class="text-3xl font-bold text-purple-600" id="weekend-count">0</p>
            </div>
        </div>

        <!-- Filters -->
        <div class="bg-white p-6 rounded-lg shadow mb-8">
            <div class="flex flex-wrap gap-4">
                <button id="filter-all" class="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition">All</button>
                <button id="filter-free" class="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition">Free</button>
                <button id="filter-paid" class="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition">Paid</button>
                <button id="filter-weekend" class="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition">Weekend</button>
                <button id="filter-today" class="px-4 py-2 bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition">Today</button>
            </div>
        </div>

        <!-- Events Grid -->
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6" id="events-grid">
            <!-- Event cards will be inserted here by JavaScript -->
            <div class="col-span-3 text-center py-12">
                <p class="text-gray-500">Loading events...</p>
            </div>
        </div>

        <!-- Footer -->
        <footer class="mt-12 pt-8 border-t border-gray-200 text-center text-sm text-gray-500">
            <p>Data updated: <span id="update-time"></span></p>
            <p>Powered by GitHub Actions & Desk Agent 2.0</p>
        </footer>
    </div>

    <script>
        // Wait for DOM to load
        document.addEventListener('DOMContentLoaded', function() {
            const eventsGrid = document.getElementById('events-grid');
            const totalCountEl = document.getElementById('total-count');
            const freeCountEl = document.getElementById('free-count');
            const paidCountEl = document.getElementById('paid-count');
            const weekendCountEl = document.getElementById('weekend-count');
            const lastUpdatedEl = document.getElementById('last-updated');
            const updateTimeEl = document.getElementById('update-time');
            
            let events = [];
            let filteredEvents = [];
            
            // Fetch events data
            fetch('events.json')
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    events = data;
                    updateStats();
                    filterAndDisplay('all'); // Show all by default
                    updateLastUpdated();
                })
                .catch(error => {
                    console.error('Error loading events:', error);
                    eventsGrid.innerHTML = `
                        <div class="col-span-3 text-center py-12">
                            <p class="text-red-500">Error loading events data</p>
                            <p class="text-gray-500">Please try again later</p>
                        </div>
                    `;
                });

            // Update statistics
            function updateStats() {
                const now = new Date();
                const today = now.toISOString().split('T')[0];
                const day = now.getDay(); // 0 = Sunday, 6 = Saturday
                
                // Calculate start of this week (Sunday) and end (Saturday)
                const sunday = new Date(now);
                sunday.setDate(now.getDate() - day);
                sunday.setHours(0, 0, 0, 0);
                
                const saturday = new Date(sunday);
                saturday.setDate(sunday.getDate() + 6);
                saturday.setHours(23, 59, 59, 999);
                
                const total = events.length;
                const free = events.filter(e => e.price === 0 || (typeof e.price === 'string' && e.price.toLowerCase() === 'free')).length;
                const paid = total - free;
                
                const weekendEvents = events.filter(e => {
                    const eventDate = new Date(e.date);
                    return eventDate >= sunday && eventDate <= saturday;
                }).length;
                
                totalCountEl.textContent = total;
                freeCountEl.textContent = free;
                paidCountEl.textContent = paid;
                weekendCountEl.textContent = weekendEvents;
            }
            
            // Update last updated timestamp
            function updateLastUpdated() {
                const now = new Date();
                lastUpdatedEl.textContent = `Last updated: ${now.toLocaleString()}`;
                updateTimeEl.textContent = new Date().toLocaleString();
            }
            
            // Filter functions
            function filterEvents(criteria) {
                const now = new Date();
                const today = now.toISOString().split('T')[0];
                
                switch (criteria) {
                    case 'free':
                        return events.filter(e => e.price === 0 || (typeof e.price === 'string' && e.price.toLowerCase() === 'free'));
                    case 'paid':
                        return events.filter(e => e.price !== 0 && (!(typeof e.price === 'string' && e.price.toLowerCase() === 'free')));
                    case 'weekend': {
                        const day = now.getDay(); // 0 = Sunday, 6 = Saturday
                        const sunday = new Date(now);
                        sunday.setDate(now.getDate() - day);
                        sunday.setHours(0, 0, 0, 0);
                        
                        const saturday = new Date(sunday);
                        saturday.setDate(sunday.getDate() + 6);
                        saturday.setHours(23, 59, 59, 999);
                        
                        return events.filter(e => {
                            const eventDate = new Date(e.date);
                            return eventDate >= sunday && eventDate <= saturday;
                        });
                    }
                    case 'today':
                        return events.filter(e => e.date === today);
                    default: // 'all'
                        return [...events];
                }
            }
            
            // Display events
            function displayEvents(eventsToShow) {
                if (eventsToShow.length === 0) {
                    eventsGrid.innerHTML = `
                        <div class="col-span-3 text-center py-12">
                            <p class="text-gray-500">No events match the selected filter</p>
                        </div>
                    `;
                    return;
                }
                
                eventsGrid.innerHTML = eventsToShow.map(event => {
                    const priceClass = event.price === 0 || (typeof event.price === 'string' && event.price.toLowerCase() === 'free') 
                        ? 'price-free' 
                        : (event.price > 0 && typeof event.price === 'number') 
                            ? 'price-paid' 
                            : 'price-unknown';
                    
                    const priceDisplay = event.price === 0 || (typeof event.price === 'string' && event.price.toLowerCase() === 'free')
                        ? 'Free'
                        : (typeof event.price === 'number' && event.price > 0)
                            ? `€${event.price}`
                            : event.price || 'Price TBD';
                    
                    return `
                        <div class="bg-white rounded-lg shadow overflow-hidden event-card hover:shadow-md transition-all">
                            <div class="p-4">
                                <h3 class="text-lg font-semibold text-gray-800 mb-2 line-clamp-2">${event.title}</h3>
                                <div class="space-y-2 text-sm text-gray-600 mb-3">
                                    <p><strong>📅 Date:</strong> <span class="font-medium">${event.date}</span></p>
                                    <p><strong>🕐 Time:</strong> <span class="font-medium">${event.time || 'TBD'}</span></p>
                                    <p><strong>📍 Venue:</strong> <span class="font-medium">${event.venue || 'TBD'}</span></p>
                                    <p><strong>💰 Price:</strong> <span class="font-medium ${priceClass}">${priceDisplay}</span></p>
                                    <p><strong>🏷️ Category:</strong> <span class="font-medium">${event.category || 'Other'}</span></p>
                                    ${event.description ? `<p class="mt-2 text-gray-700 italic line-clamp-3">${event.description}</p>` : ''}
                                </div>
                                <a href="${event.source_url}" target="_blank" rel="noopener noreferrer" class="block w-full text-center px-3 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 transition-font-medium">
                                    View Event
                                </a>
                            </div>
                        </div>
                    `;
                }).join('');
            }
            
            // Filter buttons event listeners
            document.getElementById('filter-all').addEventListener('click', () => {
                setActiveButton('filter-all');
                filteredEvents = filterEvents('all');
                displayEvents(filteredEvents);
            });
            
            document.getElementById('filter-free').addEventListener('click', () => {
                setActiveButton('filter-free');
                filteredEvents = filterEvents('free');
                displayEvents(filteredEvents);
            });
            
            document.getElementById('filter-paid').addEventListener('click', () => {
                setActiveButton('filter-paid');
                filteredEvents = filterEvents('paid');
                displayEvents(filteredEvents);
            });
            
            document.getElementById('filter-weekend').addEventListener('click', () => {
                setActiveButton('filter-weekend');
                filteredEvents = filterEvents('weekend');
                displayEvents(filteredEvents);
            });
            
            document.getElementById('filter-today').addEventListener('click', () => {
                setActiveButton('filter-today');
                filteredEvents = filterEvents('today');
                displayEvents(filteredEvents);
            });
            
            // Set active button styling
            function setActiveButton(activeId) {
                ['filter-all', 'filter-free', 'filter-paid', 'filter-weekend', 'filter-today'].forEach(id => {
                    document.getElementById(id).classList.remove('bg-blue-500', 'text-white');
                    document.getElementById(id).classList.add('bg-gray-200', 'text-gray-700');
                });
                document.getElementById(activeId).classList.add('bg-blue-500', 'text-white');
                document.getElementById(activeId).classList.remove('bg-gray-200', 'text-gray-700');
            }
            
            // Initialize with all events selected
            setActiveButton('filter-all');
        });
    </script>
</body>
</html>
EOF

# Copy any validation reports to docs/validation/
mkdir -p docs/validation
cp -f .hermes/event-scraper/desk_agent_validation_*.md docs/validation/ 2>/dev/null || true
cp -f .hermes/event-scraper/firecrawl_validation_*.md docs/validation/ 2>/dev/null || true
cp -f .hermes/event-scraper/scraper_improvement_report_*.md docs/validation/ 2>/dev/null || true || true

echo "GitHub Pages content generated successfully!"
EOF