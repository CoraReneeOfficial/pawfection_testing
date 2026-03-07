with open('templates/dashboard.html', 'r') as f:
    content = f.read()

target = """        // --- 3. Status Toggle Buttons (Groomer View - Visual Only Phase 1) ---
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

replacement = """        // --- 3. Status Toggle Buttons (Groomer View - Visual Only Phase 1) ---
        const toggles = document.querySelectorAll('.toggle-btn');
        toggles.forEach(btn => {
            btn.addEventListener('click', async function() {
                const parent = this.parentElement;
                const appointmentId = parent.getAttribute('data-appointment-id');
                const newStatus = this.getAttribute('data-status');

                // Save original text for restoring later
                const originalText = this.innerText;

                // Loading state
                const allBtns = parent.querySelectorAll('.toggle-btn');
                allBtns.forEach(b => b.disabled = true);
                this.innerText = 'Updating...';

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
                        allBtns.forEach(b => b.classList.remove('active'));
                        // Add active to clicked
                        this.classList.add('active');
                        // Show success alert
                        alert(`Status successfully updated to: ${newStatus}`);
                    } else {
                        console.error('Failed to update status');
                        alert('Failed to update status. Please try again.');
                    }
                } catch (error) {
                    console.error('Error updating status:', error);
                    alert('Error updating status. Please try again.');
                } finally {
                    // Restore original text and enable buttons
                    this.innerText = originalText;
                    allBtns.forEach(b => b.disabled = false);
                }
            });
        });"""

if target in content:
    content = content.replace(target, replacement)
    with open('templates/dashboard.html', 'w') as f:
        f.write(content)
    print("dashboard.html loading patched")
