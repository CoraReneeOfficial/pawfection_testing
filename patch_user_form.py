with open('templates/user_form.html', 'r') as f:
    content = f.read()

target = """            <div class="form-group" id="commission_group" {% if not user_data.is_groomer and mode == 'edit' %}style="display: none;"{% endif %}>
                <label for="commission_percentage">Groomer Commission (%)</label>
                <input type="number" step="0.1" id="commission_percentage" name="commission_percentage" class="form-input" value="{{ user_data.commission_percentage if user_data.commission_percentage is not none else 100.0 }}" min="0" max="100">
            </div>"""

replacement = """            <div id="commission_group" {% if not user_data.is_groomer and mode == 'edit' %}style="display: none;"{% endif %}>
                <div class="form-group">
                    <label for="commission_type">Commission Type</label>
                    <select id="commission_type" name="commission_type" class="form-input">
                        <option value="percentage" {% if user_data.commission_type == 'percentage' or not user_data.commission_type %}selected{% endif %}>Percentage (%)</option>
                        <option value="dollar" {% if user_data.commission_type == 'dollar' %}selected{% endif %}>Fixed Dollar ($)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label for="commission_amount">Commission Amount (What Groomer Keeps)</label>
                    <input type="number" step="0.01" id="commission_amount" name="commission_amount" class="form-input" value="{{ user_data.commission_amount if user_data.commission_amount is not none else 100.0 }}" min="0">
                </div>
                <div class="form-group">
                    <label for="commission_recipient_id">Who receives the remainder?</label>
                    <select id="commission_recipient_id" name="commission_recipient_id" class="form-input">
                        <option value="">-- Store (No specific Admin) --</option>
                        {% for admin in admins %}
                            <option value="{{ admin.id }}" {% if user_data.commission_recipient_id == admin.id %}selected{% endif %}>{{ admin.username }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>"""

content = content.replace(target, replacement)

with open('templates/user_form.html', 'w') as f:
    f.write(content)
