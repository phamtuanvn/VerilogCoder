`timescale 1ns/1ps

module tb;
    reg         clk;
    reg         reset;
    reg  [31:0] fcw;
    wire [31:0] phr;
    wire [7:0]  phr_int;
    wire [23:0] phr_frac;

    TopModule dut (
        .clk      (clk),
        .reset    (reset),
        .fcw      (fcw),
        .phr      (phr),
        .phr_int  (phr_int),
        .phr_frac (phr_frac)
    );

    initial clk = 0;
    always #10 clk = ~clk;

    integer mismatches = 0;
    integer total      = 0;
    integer i;
    reg [31:0] expected_phr;

    task check_phr;
        input [31:0] exp;
        begin
            total = total + 1;
            if (phr !== exp) begin
                $display("FAIL: phr=%h expected=%h", phr, exp);
                mismatches = mismatches + 1;
            end
            if (phr_int !== exp[31:24]) begin
                $display("FAIL: phr_int=%h expected=%h", phr_int, exp[31:24]);
                mismatches = mismatches + 1;
                total = total + 1;
            end
            if (phr_frac !== exp[23:0]) begin
                $display("FAIL: phr_frac=%h expected=%h", phr_frac, exp[23:0]);
                mismatches = mismatches + 1;
                total = total + 1;
            end
        end
    endtask

    initial begin
        // Test 1: Reset holds phr at 0
        reset = 1; fcw = 32'h0080_0000;
        @(posedge clk); #1; check_phr(32'h0);
        @(posedge clk); #1; check_phr(32'h0);

        // Test 2: Accumulation with FCW = 1.0
        reset = 0; fcw = 32'h0100_0000;
        expected_phr = 32'h0;
        for (i = 0; i < 8; i = i + 1) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0100_0000;
            check_phr(expected_phr);
        end

        // Test 3: Fractional accumulation FCW = 0.5
        reset = 1; @(posedge clk); #1;
        reset = 0; fcw = 32'h0080_0000;
        expected_phr = 32'h0;
        for (i = 0; i < 6; i = i + 1) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0080_0000;
            check_phr(expected_phr);
        end

        // Test 4: Overflow wrap-around
        reset = 1; @(posedge clk); #1;
        reset = 0; fcw = 32'hFFFF_FFFF;
        expected_phr = 32'h0;
        for (i = 0; i < 4; i = i + 1) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'hFFFF_FFFF;
            check_phr(expected_phr);
        end

        // Test 5: Synchronous reset mid-operation
        reset = 1; @(posedge clk); #1;
        reset = 0; fcw = 32'h0100_0000;
        expected_phr = 32'h0;
        repeat (3) begin
            @(posedge clk); #1;
            expected_phr = expected_phr + 32'h0100_0000;
        end
        check_phr(expected_phr);
        reset = 1; @(posedge clk); #1; check_phr(32'h0);
        reset = 0; @(posedge clk); #1; check_phr(32'h0100_0000);

        // Test 6: FCW change mid-run
        reset = 1; @(posedge clk); #1;
        reset = 0; fcw = 32'h0100_0000;
        expected_phr = 32'h0;
        repeat (2) begin @(posedge clk); #1; expected_phr = expected_phr + 32'h0100_0000; end
        fcw = 32'h0200_0000;
        repeat (2) begin @(posedge clk); #1; expected_phr = expected_phr + 32'h0200_0000; end
        check_phr(expected_phr);

        // Test 7: FCW = 0
        reset = 1; @(posedge clk); #1;
        reset = 0; fcw = 32'h0;
        @(posedge clk); #1; check_phr(32'h0);
        @(posedge clk); #1; check_phr(32'h0);

        $display("Mismatches: %0d in %0d samples", mismatches, total);
        $finish;
    end

    initial begin
        #100000; $display("Mismatches: 999 in 1 samples"); $finish;
    end

endmodule
