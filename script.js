document.addEventListener('DOMContentLoaded', function() {
    const dataEditorContainer = document.getElementById('data-editor-container');
    const addColBtn = document.getElementById('add-col-btn');
    const addRowBtn = document.getElementById('add-row-btn');
    const habitatSelectionButtons = document.getElementById('habitat-selection-buttons');
    const runAnalysisBtn = document.getElementById('run-analysis-btn');
    const loader = document.getElementById('loader');
    const errorMessage = document.getElementById('error-message');

    let numRows = 11;
    let numCols = 5;

    function createTable() {
        let tableHtml = '<table class="data-table">';
        for (let i = 0; i < numRows; i++) {
            tableHtml += '<tr>';
            for (let j = 0; j < numCols; j++) {
                const placeholder = (i === 0) ? `Habitat ${j + 1}` : '';
                const inputClass = (i === 0) ? 'header-input' : '';
                tableHtml += `<td><input type="text" class="${inputClass}" placeholder="${placeholder}" data-row="${i}" data-col="${j}"></td>`;
            }
            tableHtml += '</tr>';
        }
        tableHtml += '</table>';
        dataEditorContainer.innerHTML = tableHtml;
        updateHabitatButtons();
        
        // Add listener to header inputs to update buttons
        dataEditorContainer.querySelectorAll('.header-input').forEach(input => {
            input.addEventListener('input', updateHabitatButtons);
        });
    }

    function getTableData() {
        const table = dataEditorContainer.querySelector('table');
        const data = [];
        for (let i = 0; i < table.rows.length; i++) {
            const row = [];
            const inputs = table.rows[i].querySelectorAll('input');
            for (let j = 0; j < inputs.length; j++) {
                row.push(inputs[j].value);
            }
            data.push(row);
        }
        return data;
    }

    function updateHabitatButtons() {
        const headers = Array.from(dataEditorContainer.querySelectorAll('.header-input')).map((input, i) => input.value.trim() || `Relevé ${i + 1}`);
        habitatSelectionButtons.innerHTML = headers.map((name, index) =>
            `<button data-index="${index}">${name}</button>`
        ).join('');

        habitatSelectionButtons.querySelectorAll('button').forEach(button => {
            button.addEventListener('click', () => {
                button.classList.toggle('selected');
            });
        });
    }

    addColBtn.addEventListener('click', () => {
        numCols++;
        createTable();
    });

    addRowBtn.addEventListener('click', () => {
        numRows++;
        createTable();
    });

    runAnalysisBtn.addEventListener('click', async () => {
        const selectedButtons = habitatSelectionButtons.querySelectorAll('button.selected');
        if (selectedButtons.length === 0) {
            showError("Veuillez sélectionner au moins un relevé.");
            return;
        }

        loader.style.display = 'block';
        errorMessage.style.display = 'none';
        ['step2', 'step3'].forEach(id => document.getElementById(id).style.display = 'none');


        const selected_indices = Array.from(selectedButtons).map(b => parseInt(b.dataset.index));
        const releves_data = getTableData();

        try {
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ releves_data, selected_indices })
            });

            if (!response.ok) {
                const errData = await response.json();
                throw new Error(errData.error || `Erreur serveur: ${response.status}`);
            }

            const results = await response.json();
            
            if (results.message || !results.species_data || results.species_data.length === 0) {
                 showError(results.message || "Aucune donnée analysable n'a été trouvée.");
                 loader.style.display = 'none';
                 return;
            }

            displayResults(results);

        } catch (error) {
            showError(`Erreur lors de l'analyse: ${error.message}`);
        } finally {
            loader.style.display = 'none';
        }
    });

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
    }

    function displayResults(results) {
        document.getElementById('step2').style.display = 'block';
        document.getElementById('step3').style.display = 'block';
        
        renderTraitSelection(results.communalities, results.species_data);
        renderSyntaxons(results.top_syntaxons);
    }

    function renderTraitSelection(communalities, speciesData) {
        const container = document.getElementById('trait-selection-table');
        if (!communalities || communalities.length === 0) {
            container.innerHTML = "<p>Aucune donnée de communalité à afficher.</p>";
            document.getElementById('interactive-plot').innerHTML = "";
            return;
        }

        let tableHtml = '<table><tr><th>Variable</th><th>Communalité (%)</th><th>Axe X</th><th>Axe Y</th></tr>';
        communalities.forEach((item, index) => {
            const x_checked = (index === 0) ? 'checked' : '';
            const y_checked = (index === 1) ? 'checked' : '';
            tableHtml += `
                <tr>
                    <td>${item.Variable}</td>
                    <td>${item['Communalité (%)']}%</td>
                    <td><input type="radio" name="x-axis" value="${item.Variable}" ${x_checked}></td>
                    <td><input type="radio" name="y-axis" value="${item.Variable}" ${y_checked}></td>
                </tr>
            `;
        });
        tableHtml += '</table>';
        container.innerHTML = tableHtml;

        const radios = container.querySelectorAll('input[type="radio"]');
        radios.forEach(radio => radio.addEventListener('change', () => renderInteractivePlot(communalities, speciesData)));
        
        // Initial plot render
        renderInteractivePlot(communalities, speciesData);
    }
    
    function renderInteractivePlot(communalities, speciesData) {
        const x_axis = document.querySelector('input[name="x-axis"]:checked')?.value;
        const y_axis = document.querySelector('input[name="y-axis"]:checked')?.value;

        if (!x_axis || !y_axis) {
            document.getElementById('interactive-plot').innerHTML = "<p>Veuillez sélectionner les axes X et Y.</p>";
            return;
        }

        const traces = [];
        const groups = [...new Set(speciesData.map(item => item.Source_Habitat))];
        
        groups.forEach((group, i) => {
            const groupData = speciesData.filter(d => d.Source_Habitat === group);
            traces.push({
                x: groupData.map(d => d[x_axis]),
                y: groupData.map(d => d[y_axis]),
                mode: 'markers',
                type: 'scatter',
                name: group,
                text: groupData.map(d => d.Espece_User_Input_Raw),
                customdata: groupData.map(d => d.Ecologie),
                hovertemplate: '<b>%{text}</b><br>%{customdata}<extra></extra>',
                marker: { size: 8 }
            });

            // Centroid
            const x_mean = groupData.reduce((a, b) => a + b[x_axis], 0) / groupData.length;
            const y_mean = groupData.reduce((a, b) => a + b[y_axis], 0) / groupData.length;
            traces.push({
                x: [x_mean],
                y: [y_mean],
                mode: 'markers',
                type: 'scatter',
                name: `Centroïde ${group}`,
                marker: { size: 15, symbol: 'cross', color: 'white' },
                hoverinfo: 'skip'
            });
        });

        const layout = {
            title: `${y_axis} vs. ${x_axis}`,
            xaxis: { title: x_axis },
            yaxis: { title: y_axis },
            paper_bgcolor: 'var(--secondary-color)',
            plot_bgcolor: 'var(--secondary-color)',
            font: { color: 'var(--text-color)' },
            legend: { orientation: 'h', y: -0.2 }
        };

        Plotly.newPlot('interactive-plot', traces, layout, {responsive: true});
    }

    function renderSyntaxons(syntaxons) {
        const container = document.getElementById('syntaxon-display');
        if (!syntaxons || syntaxons.length === 0) {
            container.innerHTML = "<p>Aucun syntaxon correspondant trouvé.</p>";
            return;
        }

        container.innerHTML = syntaxons.map(s => `
            <div class="syntaxon-card">
                <h4>${s.name_latin} (${s.score})</h4>
                <p><b>Présents:</b></p>
                <ul class="species-list-present">
                    ${s.common_species.map(sp => `<li>${sp}</li>`).join('')}
                </ul>
                <p><b>Absents:</b></p>
                <ul class="species-list-absent">
                    ${s.absent_species.map(sp => `<li>${sp}</li>`).join('')}
                </ul>
            </div>
        `).join('');
    }

    // Initial state
    createTable();
});
