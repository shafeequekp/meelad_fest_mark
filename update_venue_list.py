from pathlib import Path
import re

p = Path('templates/program/venue_list.html')
text = p.read_text(encoding='utf-8')

# 1. Replace the old header section with the new gradient header
# Find the header by matching the unique parts
header_start = text.find('  <div class="max-w-6xl mx-auto p-4 sm:p-6 pt-24 sm:pt-28">')
header_end = text.find('    <!-- Venues Grid -->')

assert header_start != -1, f'header_start not found'
assert header_end != -1, f'header_end not found'

new_header = '''  <div class="max-w-7xl mx-auto p-4 sm:p-6 pt-24 sm:pt-28 pb-16">

    <!-- Page header -->
    <div class="bg-white shadow-sm rounded-2xl mb-6 overflow-hidden">
      <div class="bg-gradient-to-r from-emerald-600 to-teal-600 px-6 py-6 sm:px-8">
        <div class="flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div>
            <h1 class="text-2xl sm:text-3xl md:text-4xl font-extrabold text-white">✅ Venues</h1>
            <p class="text-emerald-100 mt-1 text-sm sm:text-base">
              Manage your fest venues and track scheduled programs
              {% if meelad_fest_name %}<span class="font-semibold">· {{ meelad_fest_name }}</span>{% endif %}
            </p>
          </div>
          <div>
            <button onclick="openVenueModal()"
              class="inline-flex items-center justify-center gap-2 px-5 py-3 bg-white text-emerald-700 font-bold rounded-xl shadow-lg hover:bg-emerald-50 transition text-sm sm:text-base">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
              Add Venue
            </button>
          </div>
        </div>
      </div>
      <div class="grid grid-cols-3 divide-x divide-gray-100">
        <div class="px-6 py-4">
          <p class="text-xs uppercase tracking-wide text-gray-400 font-semibold">Venues</p>
          <p class="text-2xl font-extrabold text-emerald-700">{{ venue_count }}</p>
        </div>
        <div class="px-6 py-4">
          <p class="text-xs uppercase tracking-wide text-gray-400 font-semibold">Total Programs</p>
          <p class="text-2xl font-extrabold text-indigo-700">{{ total_programs }}</p>
        </div>
        <div class="px-6 py-4">
          <p class="text-xs uppercase tracking-wide text-gray-400 font-semibold">Students</p>
          <p class="text-2xl font-extrabold text-purple-700">{{ total_students }}</p>
        </div>
      </div>
    </div>

'''

text = text[:header_start] + new_header + text[header_end:]

# 2. Replace the venue grid section
grid_start = text.find('    <!-- Venues Grid -->')
grid_end = text.find('    <!-- Add Venue Modal -->')

assert grid_start != -1, f'grid_start not found'
assert grid_end != -1, f'grid_end not found'

new_grid = '''    <!-- Venues Grid -->
    {% if venues_with_counts %}
    <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {% for venue, sched_count in venues_with_counts %}
      <a href="{% url 'venue_detail' venue.id %}"
        class="group bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden hover:shadow-lg hover:border-emerald-200 transition">
        <div class="h-28 bg-gradient-to-r from-emerald-500 to-teal-600 flex items-center justify-center">
          <span class="text-5xl font-extrabold text-white">
            {{ venue.name|slice:":1"|upper }}
          </span>
        </div>
        <div class="p-5">
          <h2 class="text-lg font-bold text-gray-800 group-hover:text-emerald-600 transition truncate">
            {{ venue.name }}
          </h2>
          <p class="text-gray-500 text-sm mt-1 line-clamp-2">
            {{ venue.description|default:"No description" }}
          </p>
          <div class="mt-3 flex items-center justify-between">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 text-xs font-semibold">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
              {{ sched_count }} program{{ sched_count|pluralize }}
            </span>
            <span class="text-emerald-600 text-sm font-semibold group-hover:translate-x-1 transition-transform">View →</span>
          </div>
        </div>
      </a>
      {% endfor %}
    </div>
    {% else %}
    <div class="bg-white border-2 border-dashed border-gray-200 rounded-2xl p-16 text-center">
      <p class="text-5xl mb-3">📍</p>
      <p class="text-gray-600 font-semibold text-lg">No venues yet</p>
      <p class="text-gray-400 mt-1">Add your first venue to start scheduling programs.</p>
      <button onclick="openVenueModal()" class="mt-4 px-5 py-2.5 bg-emerald-600 text-white font-semibold rounded-xl hover:bg-emerald-700 transition">Add Venue</button>
    </div>
    {% endif %}

'''

text = text[:grid_start] + new_grid + text[grid_end:]

# 3. Replace modal gradient and icon
text = text.replace('from-emerald-600 to-green-500', 'from-emerald-600 to-teal-600')
text = text.replace('📍</span>\n            Add Venue', '✅</span>\n            Add Venue')

p.write_text(text, encoding='utf-8')
print('TEMPLATE_UPDATED')