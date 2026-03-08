import re

with open('templates/base.html', 'r') as f:
    content = f.read()

target = """    <div id="reminder-modal"
         class="reminder-modal-overlay"
         x-show="reminderShow"
         style="display: none;">
        <!-- Modal Content -->
        <div class="reminder-modal-content" @click.outside="reminderShow = false">"""

replacement = """    <div id="reminder-modal"
         class="reminder-modal-overlay"
         x-show="reminderShow"
         style="display: none;"
         x-cloak>
        <!-- Modal Content -->
        <div class="reminder-modal-content" @click.outside="reminderShow = false">"""

content = content.replace(target, replacement)

with open('templates/base.html', 'w') as f:
    f.write(content)
