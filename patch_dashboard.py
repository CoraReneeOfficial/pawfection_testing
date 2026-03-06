with open('templates/dashboard.html', 'r') as f:
    content = f.read()

target = """                    <div class="status-toggles">
                        <button class="toggle-btn active">Checked In</button>
                        <button class="toggle-btn">In Progress</button>
                        <button class="toggle-btn">Ready</button>
                    </div>"""

replacement = """                    <div class="status-toggles" data-appointment-id="{{ next_appt.id }}">
                        <button class="toggle-btn check-in {{ 'active' if next_appt.status == 'Checked In' else '' }}" data-status="Checked In">Checked In</button>
                        <button class="toggle-btn in-progress {{ 'active' if next_appt.status == 'In Progress' else '' }}" data-status="In Progress">In Progress</button>
                        <button class="toggle-btn ready {{ 'active' if next_appt.status == 'Ready' else '' }}" data-status="Ready">Ready</button>
                    </div>"""

if target in content:
    content = content.replace(target, replacement)

target2 = """        // --- 3. Status Toggle Buttons (Groomer View - Visual Only Phase 1) ---
        const toggles = document.querySelectorAll('.toggle-btn');
        toggles.forEach(btn => {
            btn.addEventListener('click', function() {
                // Remove active from siblings
                this.parentElement.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
                // Add active to clicked
                this.classList.add('active');
            });
        });"""

replacement2 = """        // --- 3. Status Toggle Buttons (Groomer View - Visual Only Phase 1) ---
        const toggles = document.querySelectorAll('.toggle-btn');
        toggles.forEach(btn => {
            btn.addEventListener('click', async function() {
                const parent = this.parentElement;
                const appointmentId = parent.getAttribute('data-appointment-id');
                const newStatus = this.getAttribute('data-status');

                try {
                    const response = await fetch(`/api/appointments/${appointmentId}/status`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': '{{ csrf_token() }}'
                        },
                        body: JSON.stringify({ status: newStatus })
                    });

                    if (response.ok) {
                        // Remove active from siblings
                        parent.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
                        // Add active to clicked
                        this.classList.add('active');
                    } else {
                        console.error('Failed to update status');
                        alert('Failed to update status. Please try again.');
                    }
                } catch (error) {
                    console.error('Error updating status:', error);
                    alert('Error updating status. Please try again.');
                }
            });
        });"""

if target2 in content:
    content = content.replace(target2, replacement2)

with open('templates/dashboard.html', 'w') as f:
    f.write(content)
print("dashboard.html patched")
